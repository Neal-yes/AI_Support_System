from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple, Union

import httpx
from fastapi import HTTPException
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# Prometheus 指标（集中定义，供路由复用）
REQ_TOTAL = Counter(
    "tools_requests_total", "Total tool gateway requests", ["tool_type", "tool_name", "tenant"]
)
ERR_TOTAL = Counter(
    "tools_errors_total", "Total tool gateway errors", ["tool_type", "tool_name", "tenant", "reason"]
)
RL_TOTAL = Counter(
    "tools_rate_limited_total", "Total requests rate-limited", ["tool_type", "tool_name", "tenant"]
)
CB_OPEN_TOTAL = Counter(
    "tools_circuit_open_total", "Total requests blocked by circuit breaker", ["tool_type", "tool_name", "tenant"]
)
CACHE_HIT_TOTAL = Counter(
    "tools_cache_hit_total", "Total cache hits", ["tool_type", "tool_name", "tenant"]
)
RETRY_TOTAL = Counter(
    "tools_retries_total", "Total retries executed", ["tool_type", "tool_name", "tenant"]
)
LATENCY_SEC = Histogram(
    "tools_request_latency_seconds", "Tool request latency in seconds", ["tool_type", "tool_name", "tenant"]
)

SENSITIVE_KEYS = {"token", "authorization", "cookie", "api_key", "apikey", "password"}


def _mask_value(v: Any) -> Any:
    if v is None:
        return None
    s = str(v)
    if len(s) <= 4:
        return "****"
    return s[:2] + "***" + s[-2:]


def _mask_dict(d: Any) -> Any:
    if isinstance(d, dict):
        out: Dict[str, Any] = {}
        for k, v in d.items():
            if k.lower() in SENSITIVE_KEYS:
                out[k] = _mask_value(v)
            else:
                out[k] = _mask_dict(v)
        return out
    elif isinstance(d, list):
        return [_mask_dict(x) for x in d]
    else:
        return d


# 内部状态（进程内）
_RATE_BUCKET: Dict[Tuple[Any, ...], Tuple[int, float]] = {}
_SINGLEFLIGHT: Dict[Tuple[Any, ...], asyncio.Lock] = {}
_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_BREAKER: Dict[Tuple[Any, ...], Tuple[int, float]] = {}
_RATE_DEFAULT_PER_SEC = 5


def _exc_text(e: Exception) -> str:
    try:
        msg = str(e)
        if not msg:
            msg = repr(e)
    except Exception:
        msg = repr(e)
    return f"{e.__class__.__name__}: {msg}"


class _AsyncLockCtx:
    def __init__(self, lock: asyncio.Lock):
        self.lock = lock

    async def __aenter__(self):
        await self.lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.lock.release()


class ToolExecutor:
    def _stable_key(self, tenant_id: str, tool_type: str, tool_name: str, params: Dict[str, Any], normalized: Dict[str, Any]) -> str:
        try:
            base = {"params": params or {}, "normalized": normalized or {}}
            blob = json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            blob = str({"params": params, "normalized": normalized})
        h = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return ":".join([tenant_id, tool_type.lower(), tool_name.lower(), h])

    def _rate_limit_check(self, key: Union[Tuple[Any, ...], str], options: Dict[str, Any]) -> None:
        limit = options.get("rate_limit_per_sec", _RATE_DEFAULT_PER_SEC)
        if not isinstance(limit, int) or limit <= 0:
            limit = _RATE_DEFAULT_PER_SEC
        now = time.time()
        window = int(now)
        k = ("rl", key) if isinstance(key, str) else key
        count, win = _RATE_BUCKET.get(k, (0, window))
        if win != window:
            count, win = 0, window
        count += 1
        _RATE_BUCKET[k] = (count, win)
        if count > limit:
            # 指标在路由层处理标签更可靠，这里不强绑
            raise HTTPException(status_code=429, detail="Too Many Requests (rate limited)")

    def _breaker_check_and_mark(self, key: Union[Tuple[Any, ...], str], ok: Optional[bool], threshold: int, cooldown_ms: int) -> bool:
        now = time.time()
        k = ("cb", key) if isinstance(key, str) else key
        fails, until = _BREAKER.get(k, (0, 0.0))
        if now < until:
            return False
        if ok is None:
            return True
        if ok:
            _BREAKER[k] = (0, 0.0)
        else:
            fails += 1
            if fails >= max(1, threshold):
                _BREAKER[k] = (fails, now + max(100.0, cooldown_ms / 1000.0))
            else:
                _BREAKER[k] = (fails, 0.0)
        return True

    def _cache_get(self, key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
        entry = _CACHE.get(key)
        if not entry:
            return None
        expire_at, value = entry
        if time.time() > expire_at:
            _CACHE.pop(key, None)
            return None
        return value

    def _cache_put(self, key: Tuple[Any, ...], value: Dict[str, Any], ttl_ms: int) -> None:
        if ttl_ms <= 0:
            return
        _CACHE[key] = (time.time() + ttl_ms / 1000.0, value)

    def _singleflight_lock(self, key: Tuple[Any, ...]) -> _AsyncLockCtx:
        lock = _SINGLEFLIGHT.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _SINGLEFLIGHT[key] = lock
        return _AsyncLockCtx(lock)

    # 校验
    def _validate_http_get(self, params: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="params.url must be http(s) URL")
        timeout_ms = options.get("timeout_ms", 2000)
        if not isinstance(timeout_ms, int) or not (1 <= timeout_ms <= 10000):
            raise HTTPException(status_code=400, detail="options.timeout_ms must be int in [1,10000]")
        return {"url": url}

    def _validate_http_post(self, params: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="params.url must be http(s) URL")
        body = params.get("body")
        if body is not None and not isinstance(body, (dict, list, str)):
            raise HTTPException(status_code=400, detail="params.body must be dict/list/string if provided")
        timeout_ms = options.get("timeout_ms", 5000)
        if not isinstance(timeout_ms, int) or not (1 <= timeout_ms <= 15000):
            raise HTTPException(status_code=400, detail="options.timeout_ms must be int in [1,15000]")
        return {"url": url, "has_body": body is not None}

    def _validate(self, tool_type: str, tool_name: str, params: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
        key = (tool_type.lower(), tool_name.lower())
        if key == ("http_get", "simple") or key == ("http", "http_get"):
            return self._validate_http_get(params, options)
        if key == ("http_post", "simple") or key == ("http", "http_post"):
            return self._validate_http_post(params, options)
        if not tool_type or not tool_name:
            raise HTTPException(status_code=400, detail="tool_type/tool_name is required")
        return {}

    async def _do_http_get(self, params: Dict[str, Any], options: Dict[str, Any], normalized: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url")
        headers = params.get("headers") if isinstance(params, dict) else None
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("params.headers must be an object")
        timeout_ms = int(options.get("timeout_ms", 2000))
        max_chars = int(options.get("resp_max_chars", 2048))
        async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        body = resp.text or ""
        if max_chars > 0 and len(body) > max_chars:
            body = body[:max_chars]
        return {
            "http": {"status_code": resp.status_code, "ok": resp.is_success, "url": str(resp.request.url)},
            "message": "http_get executed",
            "body": body,
            "normalized": normalized,
        }

    async def _do_http_post(self, params: Dict[str, Any], options: Dict[str, Any], normalized: Dict[str, Any]) -> Dict[str, Any]:
        url = params.get("url")
        headers = params.get("headers") if isinstance(params, dict) else None
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("params.headers must be an object")
        timeout_ms = int(options.get("timeout_ms", 2000))
        max_chars = int(options.get("resp_max_chars", 2048))
        content_type = str(options.get("content_type", "application/json")).lower()
        raw_body = params.get("body") if isinstance(params, dict) else None
        async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
            if content_type == "application/json":
                json_body = None
                if isinstance(raw_body, (dict, list)):
                    json_body = raw_body
                elif isinstance(raw_body, str) and raw_body.strip():
                    try:
                        json_body = json.loads(raw_body)
                    except Exception:
                        headers = {**(headers or {}), "Content-Type": "application/json"}
                        resp = await client.post(url, headers=headers, content=raw_body)
                        body = resp.text or ""
                        if max_chars > 0 and len(body) > max_chars:
                            body = body[:max_chars]
                        return {
                            "http": {"status_code": resp.status_code, "ok": resp.is_success, "url": str(resp.request.url)},
                            "message": "http_post executed (raw content)",
                            "body": body,
                            "normalized": normalized,
                        }
                resp = await client.post(url, headers=headers, json=json_body)
            else:
                data = raw_body if isinstance(raw_body, (str, bytes)) else (
                    json.dumps(raw_body) if raw_body is not None else None
                )
                headers = {**(headers or {}), "Content-Type": content_type}
                resp = await client.post(url, headers=headers, content=data)
        body = resp.text or ""
        if max_chars > 0 and len(body) > max_chars:
            body = body[:max_chars]
        return {
            "http": {"status_code": resp.status_code, "ok": resp.is_success, "url": str(resp.request.url)},
            "message": "http_post executed",
            "body": body,
            "normalized": normalized,
        }

    async def execute(self, tenant_id: str, tool_type: str, tool_name: str, params: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
        # 校验与标准化
        normalized = self._validate(tool_type, tool_name, params, options)
        # 标签与键
        tenant_label = (tenant_id or "_anon_")
        labels = {"tool_type": tool_type.lower(), "tool_name": tool_name.lower(), "tenant": tenant_label}
        REQ_TOTAL.labels(**labels).inc()
        start_ts = time.perf_counter()
        key_base = self._stable_key(tenant_label, tool_type, tool_name, params, normalized)
        # 限流
        try:
            self._rate_limit_check((labels["tool_type"], labels["tool_name"], tenant_label, key_base), options)
        except HTTPException:
            RL_TOTAL.labels(**labels).inc()
            LATENCY_SEC.labels(**labels).observe(max(0.0, time.perf_counter() - start_ts))
            raise
        # 熔断预检查
        circuit_threshold = int(options.get("circuit_threshold", 3))
        circuit_cooldown_ms = int(options.get("circuit_cooldown_ms", 5000))
        if not self._breaker_check_and_mark(key_base, ok=None, threshold=circuit_threshold, cooldown_ms=circuit_cooldown_ms):
            CB_OPEN_TOTAL.labels(**labels).inc()
            LATENCY_SEC.labels(**labels).observe(max(0.0, time.perf_counter() - start_ts))
            raise HTTPException(status_code=503, detail="Service temporarily unavailable (circuit open)")
        # 缓存
        cache_ttl_ms = int(options.get("cache_ttl_ms", 0))
        cache_key = ("cache", key_base)
        if cache_ttl_ms > 0:
            cached = self._cache_get(cache_key)
            if cached is not None:
                CACHE_HIT_TOTAL.labels(**labels).inc()
                LATENCY_SEC.labels(**labels).observe(max(0.0, time.perf_counter() - start_ts))
                logger.info("cache_hit", extra={"labels": labels, "key": key_base})
                return {**cached, "from_cache": True}
        # singleflight
        async with self._singleflight_lock(("sf", key_base)):
            masked_params = _mask_dict(params)
            masked_options = _mask_dict(options)
            # 重试
            retry_max = int(options.get("retry_max", 0))
            backoff_ms = int(options.get("retry_backoff_ms", 100))
            attempt = 0
            last_err: Optional[str] = None
            while True:
                attempt += 1
                try:
                    if bool(options.get("simulate_fail", False)):
                        raise RuntimeError("simulated failure")
                    # 执行
                    if tool_type.lower() == "http_get":
                        result = await self._do_http_get(params, options, normalized)
                    elif tool_type.lower() == "http_post":
                        result = await self._do_http_post(params, options, normalized)
                    else:
                        result = {"message": "tool invoked (validated)", "normalized": normalized}
                    # 缓存写入
                    if cache_ttl_ms > 0:
                        self._cache_put(cache_key, result, cache_ttl_ms)
                    # 熔断成功标记
                    self._breaker_check_and_mark(("cb", key_base), ok=True, threshold=circuit_threshold, cooldown_ms=circuit_cooldown_ms)
                    LATENCY_SEC.labels(**labels).observe(max(0.0, time.perf_counter() - start_ts))
                    logger.info("tool_success", extra={"labels": labels, "attempt": attempt})
                    return {**result, "from_cache": False, "echo": masked_params, "options": masked_options}
                except Exception as e:
                    last_err = _exc_text(e)
                    if attempt > retry_max:
                        self._breaker_check_and_mark(("cb", key_base), ok=False, threshold=circuit_threshold, cooldown_ms=circuit_cooldown_ms)
                        ERR_TOTAL.labels(**labels, reason="exec_failure").inc()
                        LATENCY_SEC.labels(**labels).observe(max(0.0, time.perf_counter() - start_ts))
                        logger.warning("tool_failure", extra={"labels": labels, "attempt": attempt, "error": last_err})
                        raise HTTPException(status_code=502, detail=f"tool execution failed: {last_err}")
                    RETRY_TOTAL.labels(**labels).inc()
                    logger.info("tool_retry", extra={"labels": labels, "attempt": attempt, "error": last_err})
                    await asyncio.sleep(max(0.0, backoff_ms * attempt / 1000.0))


# 单例执行器
executor = ToolExecutor()
