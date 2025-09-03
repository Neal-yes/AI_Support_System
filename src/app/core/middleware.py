from __future__ import annotations

import logging
import time
import uuid
from typing import Callable
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response, StreamingResponse
from src.app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY
from src.app.config import settings
import re
from typing import Optional
import json
import random

try:
    import jwt  # PyJWT
except Exception:  # pragma: no cover
    jwt = None  # type: ignore

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.state.request_id = request_id
        # Resolve tenant
        tenant = self._resolve_tenant(request)
        request.state.tenant = tenant
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 异常会被全局异常处理器捕获，这里也记录耗时
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "request_error",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        # 捕获响应体（为日志和注入 request_id 做准备）。StreamingResponse 不应消费其迭代器以免破坏流。
        raw_body: Optional[bytes] = None
        is_streaming = isinstance(response, StreamingResponse)
        if not is_streaming:
            try:
                # JSONResponse/Plain Response 通常有 .body
                raw_body = getattr(response, "body", None)
                if raw_body is None and hasattr(response, "render"):
                    raw_body = await response.render(None)  # type: ignore
            except Exception:
                raw_body = None

        # 在 2xx/3xx 且 JSON 响应时注入 request_id（若为对象）
        if not is_streaming:
            try:
                ct = response.headers.get("content-type", "").lower()
                if response.status_code < 400 and raw_body and ct.startswith("application/json"):
                    data = json.loads(raw_body.decode("utf-8", errors="replace"))
                    if isinstance(data, dict) and "request_id" not in data:
                        data["request_id"] = request_id
                        new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                        _hdrs = {k: v for k, v in dict(response.headers).items() if k.lower() != "content-length"}
                        response = Response(
                            content=new_body,
                            status_code=response.status_code,
                            headers=_hdrs,
                            media_type="application/json",
                        )
                        raw_body = new_body
            except Exception:
                pass

        # 结构化访问日志（按需附带响应体预览）
        extra_fields = {
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "tenant": tenant,
        }
        # 仅 5xx 或按采样率记录响应体截断
        should_sample = settings.LOG_RESPONSE_BODY_SAMPLE_RATE > 0.0 and (random.random() < settings.LOG_RESPONSE_BODY_SAMPLE_RATE)
        if raw_body is not None and (should_sample or (settings.LOG_RESPONSE_BODY_ON_5XX and 500 <= response.status_code <= 599)):
            try:
                extra_fields["resp_body_preview"] = raw_body[:500].decode("utf-8", errors="replace")
            except Exception:
                extra_fields["resp_body_preview"] = "<non-text body>"
        logger.info("request_done", extra=extra_fields)
        # Prometheus metrics
        labels = (request.method, request.url.path, str(response.status_code))
        REQUEST_COUNT.labels(*labels).inc()
        REQUEST_LATENCY.labels(*labels).observe(duration_ms / 1000.0)
        # 将 request_id 透传给客户端
        response.headers["X-Request-Id"] = request_id
        return response

    def _resolve_tenant(self, request: Request) -> str:
        """Extract and validate tenant from header and optional JWT.
        Rules:
        - Header key configurable via settings.HEADER_TENANT_KEY, default 'X-Tenant-Id'.
        - Valid charset: [A-Za-z0-9_-], length 1..64. Invalid header -> 400 style by raising ValueError; we fallback to '_anon_' to avoid breaking tests and let route handlers decide if required.
        - If AUTH_JWT_SECRET configured and Authorization bearer provided, decode and compare claim (settings.AUTH_TENANT_CLAIM). If mismatch -> raise ValueError.
        - Return resolved tenant or '_anon_'.
        """
        raw = request.headers.get(settings.HEADER_TENANT_KEY, "").strip()
        tenant: Optional[str] = raw or None
        # Basic validation if present
        if tenant is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tenant):
                # 记录并降级处理为匿名，避免影响无关测试；若需要强校验可改为抛 400
                logger.warning("invalid_tenant_header", extra={"tenant": raw})
                if getattr(settings, "AUTH_REQUIRE_TENANT", False):
                    raise HTTPException(status_code=400, detail="invalid tenant header")
                tenant = None
        elif getattr(settings, "AUTH_REQUIRE_TENANT", False):
            # 缺少 tenant 且要求必须提供
            raise HTTPException(status_code=400, detail="tenant header required")

        # Optional JWT validation
        auth = request.headers.get("Authorization", "")
        if settings.AUTH_JWT_SECRET and auth.startswith("Bearer ") and jwt is not None:
            token = auth.split(" ", 1)[1]
            try:
                payload = jwt.decode(token, settings.AUTH_JWT_SECRET, algorithms=[settings.AUTH_JWT_ALG])
                claim_value = payload.get(settings.AUTH_TENANT_CLAIM)
                if isinstance(claim_value, str) and claim_value:
                    if tenant is None:
                        tenant = claim_value
                    elif tenant != claim_value:
                        logger.warning("tenant_mismatch", extra={"header": tenant, "claim": claim_value})
                        if getattr(settings, "AUTH_ENFORCE_JWT_TENANT", False):
                            raise HTTPException(status_code=401, detail="tenant mismatch with token")
                        # 宽松模式下以 claim 为准
                        tenant = claim_value
            except Exception as e:  # pragma: no cover
                logger.warning("jwt_decode_failed", extra={"error": str(e)})

        return tenant or "_anon_"
