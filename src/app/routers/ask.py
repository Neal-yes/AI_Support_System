from __future__ import annotations

from typing import Any, Dict, List, Optional
import time
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.app.clients import ollama
from src.app.clients import qdrant as qcli
from src.app.config import settings
from src.app.core.metrics import (
    EMBED_SECONDS,
    RAG_RETRIEVAL_SECONDS,
    LLM_GENERATE_SECONDS,
    RAG_MATCHES_TOTAL,
)

router = APIRouter(prefix="/api/v1", tags=["ask"])


class AskRequest(BaseModel):
    query: str
    use_rag: bool = True
    top_k: Optional[int] = None
    collection: Optional[str] = None
    model: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None


def _build_prompt(query: str, contexts: List[str]) -> str:
    if not contexts:
        return f"问题：{query}\n请用不超过两句话作答。"
    ctx = "\n\n".join(c for c in contexts)
    return (
        f"上下文：{ctx}\n"
        f"问题：{query}\n"
        "请仅依据上下文，用不超过两句话简洁作答。"
    )


def _prepare_contexts(scored: list, max_docs: int = 1, per_doc_max_chars: int = 180, total_max_chars: int = 480):
    seen = set()
    contexts: List[str] = []
    sources: List[Dict[str, Any]] = []
    total_chars = 0
    for s in scored:
        pl = getattr(s, "payload", None) or {}
        txt = pl.get("text") if isinstance(pl, dict) else None
        if not txt:
            continue
        key = str(txt)
        if key in seen:
            continue
        seen.add(key)
        snippet = key[:per_doc_max_chars]
        if total_chars + len(snippet) > total_max_chars:
            break
        contexts.append(snippet)
        total_chars += len(snippet)
        sources.append({"id": s.id, "score": s.score, "payload": pl})
        if len(contexts) >= max_docs:
            break
    return contexts, sources


class PreflightRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    collection: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None


@router.post("/rag/preflight")
async def rag_preflight(req: PreflightRequest, request: Request) -> Dict[str, Any]:
    """Embedding + retrieval only; return stats for UI tips.

    Response fields:
    - ok: bool
    - contexts_count: int
    - ctx_total_len: int
    - max_score: float | None
    - avg_score: float | None
    - collection: str
    """
    tenant = getattr(request.state, "tenant", "_anon_")
    request_id = getattr(request.state, "request_id", "")
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K

    # 1) embeddings（软失败：不抛 500，返回 ok=false）
    try:
        emb_model = (getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL)
        qvecs = await ollama.embeddings([req.query], model=emb_model)
    except Exception as e:
        return {
            "ok": False,
            "error": f"preflight embed failed: {type(e).__name__}: {e}",
            "contexts_count": 0,
            "ctx_total_len": 0,
            "max_score": None,
            "avg_score": None,
            "collection": coll,
            "meta": {"tenant": tenant, "request_id": request_id},
        }
    if not qvecs or not qvecs[0]:
        return {
            "ok": False,
            "error": "preflight embed returned empty vector",
            "contexts_count": 0,
            "ctx_total_len": 0,
            "max_score": None,
            "avg_score": None,
            "collection": coll,
            "meta": {"tenant": tenant, "request_id": request_id},
        }

    # 2) collection check
    if not qcli.collection_exists(coll):
        return {
            "ok": True,
            "contexts_count": 0,
            "ctx_total_len": 0,
            "max_score": None,
            "avg_score": None,
            "collection": coll,
            "meta": {"tenant": tenant, "request_id": request_id},
        }

    # 3) retrieval（软失败：不抛 500，返回 ok=false）
    try:
        scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
    except Exception as e:
        return {
            "ok": False,
            "error": f"preflight retrieval failed: {type(e).__name__}: {e}",
            "contexts_count": 0,
            "ctx_total_len": 0,
            "max_score": None,
            "avg_score": None,
            "collection": coll,
            "meta": {"tenant": tenant, "request_id": request_id},
        }

    contexts, sources = _prepare_contexts(scored)
    ctx_total_len = sum(len(c) for c in contexts)
    scores = [getattr(s, "score", None) for s in scored if getattr(s, "score", None) is not None]
    max_score = max(scores) if scores else None
    avg_score = (sum(scores) / len(scores)) if scores else None

    return {
        "ok": True,
        "contexts_count": len(contexts),
        "ctx_total_len": ctx_total_len,
        "max_score": max_score,
        "avg_score": avg_score,
        "collection": coll,
        "meta": {"tenant": tenant, "request_id": request_id},
        "sources": sources,
    }


@router.post("/ask")
async def ask(req: AskRequest, request: Request) -> Dict[str, Any]:
    tenant = getattr(request.state, "tenant", "_anon_")
    request_id = getattr(request.state, "request_id", "")

    # Plain LLM path
    if not req.use_rag:
        opts: Dict[str, Any] = dict(req.options or {})
        if "num_predict" not in opts:
            opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
        # Plan B conservative defaults for faster, stable outputs
        opts.setdefault("temperature", 0.4)
        opts.setdefault("top_p", 0.9)
        opts.setdefault("repeat_penalty", 1.05)
        t0 = time.monotonic()
        try:
            resp = await ollama.generate(
                req.query,
                model=req.model or settings.OLLAMA_MODEL,
                **opts,
            )
        except Exception as e:
            # 记录失败耗时并返回详细错误，便于 CI Smoke 调试
            LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="false").observe(max(time.monotonic() - t0, 0.0))
            raise HTTPException(status_code=500, detail=f"plain generation failed: {type(e).__name__}: {e}")
        LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="false").observe(max(time.monotonic() - t0, 0.0))
        return {
            "response": resp.get("response", ""),
            "sources": [],
            "meta": {"tenant": tenant, "request_id": request_id, "use_rag": False},
        }

    # RAG path
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K

    # embed query (force dedicated embed model to ensure dim match and speed)
    t_emb = time.monotonic()
    emb_model = (getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL)
    qvecs = await ollama.embeddings([req.query], model=emb_model)
    EMBED_SECONDS.labels(model=emb_model).observe(max(time.monotonic() - t_emb, 0.0))
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")

    if not qcli.collection_exists(coll):
        # 返回无命中但不报错，便于前端处理
        return {
            "response": "未在文档中找到相关信息",
            "sources": [],
            "meta": {"tenant": tenant, "request_id": request_id, "use_rag": True, "collection": coll, "matches": 0},
        }

    # Retrieval
    try:
        t_ret = time.monotonic()
        scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
        RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"rag retrieval failed: {e}")

    contexts, sources = _prepare_contexts(scored)
    if not contexts:
        # No usable contexts; return graceful response without LLM call
        RAG_MATCHES_TOTAL.labels(collection=coll, has_match="false").inc()
        return {
            "response": "未在文档中找到相关信息",
            "sources": [],
            "meta": {"tenant": tenant, "request_id": request_id, "use_rag": True, "collection": coll, "top_k": top_k, "match": False},
        }

    prompt = _build_prompt(req.query, contexts)

    # Generation
    opts: Dict[str, Any] = dict(req.options or {})
    if "num_predict" not in opts:
        opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
    # Plan B conservative defaults for faster, stable outputs
    opts.setdefault("temperature", 0.4)
    opts.setdefault("top_p", 0.9)
    opts.setdefault("repeat_penalty", 1.05)
    try:
        t_gen = time.monotonic()
        resp = await ollama.generate(
            prompt,
            model=req.model or settings.OLLAMA_MODEL,
            **opts,
        )
        LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="false").observe(max(time.monotonic() - t_gen, 0.0))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"rag generation failed: {type(e).__name__}: {e}")

    RAG_MATCHES_TOTAL.labels(collection=coll, has_match=str(bool(scored)).lower()).inc()

    return {
        "response": resp.get("response", ""),
        "sources": sources,
        "meta": {
            "tenant": tenant,
            "request_id": request_id,
            "use_rag": True,
            "collection": coll,
            "top_k": top_k,
            "match": bool(scored),
        },
    }


@router.post("/ask/stream")
async def ask_stream(req: AskRequest, request: Request) -> StreamingResponse:
    tenant = getattr(request.state, "tenant", "_anon_")
    request_id = getattr(request.state, "request_id", "")

    async def _sse_wrapper(gen):
        # immediate handshake event to help proxies/clients flush headers
        yield b"data: [started]\n\n"
        try:
            async for chunk in gen:
                if not chunk:
                    continue
                if isinstance(chunk, str):
                    chunk_b = chunk.encode("utf-8")
                else:
                    chunk_b = bytes(chunk)
                yield b"data: " + chunk_b + b"\n\n"
            yield b"data: [done]\n\n"
        except Exception as e:
            # emit error and close
            msg = f"[error]: {type(e).__name__}: {e}"
            yield ("data: " + msg + "\n\n").encode("utf-8")

    async def _limit_stream(gen, *, time_limit_ms: Optional[int] = None, max_tokens_streamed: Optional[int] = None):
        start_ts = time.perf_counter()
        tokens = 0
        async for chunk in gen:
            yield chunk
            # 以“分片”为单位近似 token 数，避免解析成本
            tokens += 1
            if max_tokens_streamed is not None and tokens >= max_tokens_streamed:
                break
            if time_limit_ms is not None:
                elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
                if elapsed_ms >= time_limit_ms:
                    break

    async def _with_heartbeat(gen, *, time_limit_ms: Optional[int], max_tokens_streamed: Optional[int], heartbeat_ms: Optional[int]):
        """Wrap a base async generator to inject heartbeat events when idle, and enforce limits."""
        queue: asyncio.Queue = asyncio.Queue()

        async def _pump():
            try:
                async for chunk in gen:
                    await queue.put(("data", chunk))
            except Exception as e:
                await queue.put(("error", e))
            finally:
                await queue.put(("eof", None))

        # start background pump
        asyncio.create_task(_pump())

        # emit started
        yield b"data: [started]\n\n"

        start_ts = time.perf_counter()
        tokens = 0
        while True:
            timeout = (heartbeat_ms / 1000.0) if heartbeat_ms else None
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                # heartbeat only when enabled
                if heartbeat_ms:
                    yield b"data: [heartbeat]\n\n"
                # also check time limit after heartbeat
                if time_limit_ms is not None:
                    elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
                    if elapsed_ms >= time_limit_ms:
                        break
                continue

            if kind == "data":
                if payload:
                    if isinstance(payload, str):
                        chunk_b = payload.encode("utf-8")
                    else:
                        chunk_b = bytes(payload)
                    yield b"data: " + chunk_b + b"\n\n"
                    tokens += 1
                    if max_tokens_streamed is not None and tokens >= max_tokens_streamed:
                        break
                # time limit check after data
                if time_limit_ms is not None:
                    elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
                    if elapsed_ms >= time_limit_ms:
                        break
            elif kind == "error":
                msg = f"[error]: {type(payload).__name__}: {payload}"
                yield ("data: " + msg + "\n\n").encode("utf-8")
                break
            elif kind == "eof":
                break

        # graceful end
        yield b"data: [done]\n\n"

    headers = {
        "x-request-id": request_id,
        "x-tenant": tenant,
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    # Plain LLM path
    if not req.use_rag:
        opts: Dict[str, Any] = dict(req.options or {})
        # 限制与心跳（可选）
        time_limit_ms = opts.pop("time_limit_ms", None)
        max_tokens_streamed = opts.pop("max_tokens_streamed", None)
        if max_tokens_streamed is None:
            max_tokens_streamed = 12
        heartbeat_ms = opts.pop("heartbeat_ms", None)
        if "num_predict" not in opts:
            opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
        # Plan B conservative defaults
        opts.setdefault("temperature", 0.4)
        opts.setdefault("top_p", 0.9)
        opts.setdefault("repeat_penalty", 1.05)
        opts.setdefault("stop", ["\n\n["])
        gen = ollama.generate_stream(
            req.query,
            model=req.model or settings.OLLAMA_MODEL,
            **opts,
        )
        wrapped = _with_heartbeat(gen, time_limit_ms=time_limit_ms, max_tokens_streamed=max_tokens_streamed, heartbeat_ms=heartbeat_ms)
        return StreamingResponse(wrapped, media_type="text/event-stream; charset=utf-8", headers=headers)


    # RAG path (emit started immediately; heartbeat during embed/retrieval; then stream generation)
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K

    async def _rag_flow():
        logger = logging.getLogger("ask_stream")
        # Always start the SSE early to flush headers
        yield b"data: [started]\n\n"

        # Extract options early so we can reuse heartbeat for pre-LLM phases
        opts: Dict[str, Any] = dict(req.options or {})
        time_limit_ms = opts.pop("time_limit_ms", None)
        max_tokens_streamed = opts.pop("max_tokens_streamed", None)
        if max_tokens_streamed is None:
            max_tokens_streamed = 3
        heartbeat_ms = opts.pop("heartbeat_ms", None)
        if "num_predict" not in opts:
            # 更短输出以提高完成概率
            opts["num_predict"] = 2
        # 更保守、更快出首包（极限收紧）
        opts.setdefault("temperature", 0.1)
        opts.setdefault("top_p", 0.65)
        opts.setdefault("repeat_penalty", 1.05)
        opts.setdefault("num_ctx", 320)
        opts.setdefault("stop", ["\n\n["])

        # 1) Embedding (async) with periodic heartbeats
        # 强制使用专用嵌入模型，避免因生成模型不同导致维度不一致
        emb_model = (getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL)
        emb_task = asyncio.create_task(ollama.embeddings([req.query], model=emb_model))
        if heartbeat_ms and heartbeat_ms > 0:
            interval = max(heartbeat_ms / 1000.0, 0.1)
            while not emb_task.done():
                await asyncio.sleep(interval)
                if not emb_task.done():
                    yield b"data: [heartbeat]\n\n"
        qvecs = await emb_task
        if not qvecs or not qvecs[0]:
            yield b"data: [error]: EmbeddingError: failed to get query embedding\n\n"
            yield b"data: [done]\n\n"
            return

        # 2) If no collection, return a graceful message (check in thread)
        exists = await asyncio.to_thread(qcli.collection_exists, coll)
        if not exists:
            yield "data: 未在文档中找到相关信息\n\n".encode("utf-8")
            yield b"data: [done]\n\n"
            return

        # Validate vector dimension to avoid Qdrant 400 errors
        dim = len(qvecs[0])
        try:
            info = await asyncio.to_thread(qcli.get_collection_info, coll)
            expected = (
                info.get("config", {}).get("params", {}).get("vectors", {}).get("size")
                or info.get("params", {}).get("vectors", {}).get("size")
                or info.get("params", {}).get("size")
                or (info.get("vectors", {}) if isinstance(info.get("vectors", {}), dict) else {}).get("size")
                or 0
            )
            expected = int(expected or 0)
        except Exception:
            expected = 0
        if expected and expected != dim:
            msg = f"向量维度不匹配：集合期望 {expected}，查询为 {dim}；请使用相同嵌入模型重建集合或切换到匹配的集合。"
            yield ("data: " + msg + "\n\n").encode("utf-8")
            yield b"data: [done]\n\n"
            return

        # 3) Retrieval with heartbeats (run blocking search in thread)
        async def _search_thread():
            return await asyncio.to_thread(qcli.search_vectors, coll, qvecs[0], top_k, req.filters)

        search_task = asyncio.create_task(_search_thread())
        if heartbeat_ms and heartbeat_ms > 0:
            interval = max(heartbeat_ms / 1000.0, 0.1)
            while not search_task.done():
                await asyncio.sleep(interval)
                if not search_task.done():
                    yield b"data: [heartbeat]\n\n"
        try:
            scored = await search_task
        except Exception as e:
            msg = f"[error]: QdrantSearchError: {e}"
            yield ("data: " + msg + "\n\n").encode("utf-8")
            yield b"data: [done]\n\n"
            return

        contexts, _ = _prepare_contexts(scored)
        ctx_total_len = sum(len(c) for c in contexts)
        prompt = _build_prompt(req.query, contexts)

        # 3.5) 检索短路：上下文缺失或过短，直接走非RAG
        if not contexts or ctx_total_len < 80:
            try:
                logger.info("rag_short_circuit to_plain reason=%s ctx_total_len=%d", 
                            "no_contexts" if not contexts else "too_short", ctx_total_len)
            except Exception:
                pass
            plain_opts: Dict[str, Any] = dict(opts)
            plain_opts["num_predict"] = min(plain_opts.get("num_predict", 3), 3)
            plain_gen = ollama.generate_stream(
                req.query,
                model=req.model or settings.OLLAMA_MODEL,
                **plain_opts,
            )
            async for chunk in _with_heartbeat(plain_gen, time_limit_ms=time_limit_ms, max_tokens_streamed=max_tokens_streamed, heartbeat_ms=heartbeat_ms):
                yield chunk
            return

        # 4) 并行竞速：RAG 与 非RAG 同时尝试，8 秒内谁先出首 token 用谁
        t_race_start = time.perf_counter()
        rag_gen = ollama.generate_stream(
            prompt,
            model=req.model or settings.OLLAMA_MODEL,
            **opts,
        )
        plain_opts: Dict[str, Any] = dict(opts)
        # 非 RAG 更短一些
        plain_opts["num_predict"] = min(plain_opts.get("num_predict", 4), 4)
        plain_gen = ollama.generate_stream(
            req.query,
            model=req.model or settings.OLLAMA_MODEL,
            **plain_opts,
        )

        t_rag = asyncio.create_task(rag_gen.__anext__())
        t_plain = asyncio.create_task(plain_gen.__anext__())
        done, pending = await asyncio.wait({t_rag, t_plain}, timeout=8.0, return_when=asyncio.FIRST_COMPLETED)

        winner = None
        first_chunk = None
        if not done:
            # 都没首包，取消两路，直接走非RAG全程
            for t in pending:
                t.cancel()
            try:
                await rag_gen.aclose()
            except Exception:
                pass
            try:
                logger.info("rag_race_no_first_token elapsed_ms=%.2f fallback=plain", (time.perf_counter()-t_race_start)*1000.0)
            except Exception:
                pass
            # 重新开一个更短的非RAG生成器
            fb_opts: Dict[str, Any] = dict(plain_opts)
            fb_gen = ollama.generate_stream(
                req.query,
                model=req.model or settings.OLLAMA_MODEL,
                **fb_opts,
            )
            async for chunk in _with_heartbeat(fb_gen, time_limit_ms=time_limit_ms, max_tokens_streamed=max_tokens_streamed, heartbeat_ms=heartbeat_ms):
                yield chunk
            return

        # 有胜者
        if t_rag in done:
            winner = "rag"
            try:
                first_chunk = t_rag.result()
            except Exception:
                first_chunk = None
        else:
            winner = "plain"
            try:
                first_chunk = t_plain.result()
            except Exception:
                first_chunk = None

        try:
            logger.info("rag_race_winner=%s elapsed_ms=%.2f", winner, (time.perf_counter()-t_race_start)*1000.0)
        except Exception:
            pass

        # 取消败者
        loser_task = t_plain if winner == "rag" else t_rag
        loser_gen = plain_gen if winner == "rag" else rag_gen
        if not loser_task.done():
            loser_task.cancel()
        try:
            await loser_gen.aclose()
        except Exception:
            pass

        # 输出首片
        if first_chunk is not None:
            if isinstance(first_chunk, str):
                first_b = first_chunk.encode("utf-8")
            else:
                first_b = bytes(first_chunk)
            yield first_b

        # 继续用带心跳与限制的包装器输出
        live_gen = rag_gen if winner == "rag" else plain_gen
        wrapped = _with_heartbeat(live_gen, time_limit_ms=time_limit_ms, max_tokens_streamed=max_tokens_streamed, heartbeat_ms=heartbeat_ms)
        async for chunk in wrapped:
            yield chunk

    return StreamingResponse(_rag_flow(), media_type="text/event-stream; charset=utf-8", headers=headers)


@router.get("/debug/stream")
async def debug_stream(request: Request) -> StreamingResponse:
    tenant = getattr(request.state, "tenant", "_anon_")
    request_id = getattr(request.state, "request_id", "")

    async def _gen():
        yield b"data: [started]\n\n"
        for i in range(1, 11):
            msg = f"tick {i}"
            yield ("data: " + msg + "\n\n").encode("utf-8")
            await asyncio.sleep(0.5)
        yield b"data: [done]\n\n"

    headers = {
        "x-request-id": request_id,
        "x-tenant": tenant,
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(_gen(), media_type="text/event-stream; charset=utf-8", headers=headers)


@router.get("/debug/warmup")
async def debug_warmup(request: Request) -> Dict[str, Any]:
    """Trigger a short non-stream generation to warm up the model and underlying runtime.

    Returns a JSON payload with ok flag and latency_ms.
    """
    tenant = getattr(request.state, "tenant", "_anon_")
    request_id = getattr(request.state, "request_id", "")
    opts: Dict[str, Any] = {"num_predict": 8}
    t0 = time.perf_counter()
    try:
        _ = await ollama.generate(
            "warmup",
            model=settings.OLLAMA_MODEL,
            **opts,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return {"ok": True, "latency_ms": round(latency_ms, 2), "meta": {"tenant": tenant, "request_id": request_id}}
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        # surface error but keep 200 for observability during CI/smoke
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "latency_ms": round(latency_ms, 2), "meta": {"tenant": tenant, "request_id": request_id}}
