from __future__ import annotations

from typing import Any, Dict, Optional, List
import json
import time
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse, Response
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

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


@router.post("")
async def chat(req: ChatRequest) -> Dict[str, Any]:
    # 注入默认生成参数（如未提供）
    opts: Dict[str, Any] = dict(req.options or {})
    if "num_predict" not in opts:
        opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
    t0 = time.monotonic()
    resp = await ollama.generate(
        req.prompt,
        model=req.model or settings.OLLAMA_MODEL,
        # 使用客户端内置的 keep_alive 与 timeout 默认值
        **opts,
    )
    LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="false").observe(
        max(time.monotonic() - t0, 0.0)
    )
    # Ollama /api/generate returns {response: str, ...}
    return {
        "model": req.model or settings.OLLAMA_MODEL,
        "response": resp.get("response", ""),
        "raw": resp,
    }


@router.post("/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    opts: Dict[str, Any] = dict(req.options or {})
    if "num_predict" not in opts:
        opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
    async def gen():
        t0 = time.monotonic()
        try:
            async for chunk in ollama.generate_stream(
                req.prompt,
                model=req.model or settings.OLLAMA_MODEL,
                **opts,
            ):
                yield chunk
        finally:
            LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="true").observe(
                max(time.monotonic() - t0, 0.0)
            )
    # 以 text/plain 流返回，便于在终端实时显示；若需要 SSE 可后续扩展为 text/event-stream
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # 对部分反向代理禁用缓冲
    }
    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8", headers=headers)


@router.post("/stream_sse")
async def chat_stream_sse(req: ChatRequest) -> StreamingResponse:
    opts: Dict[str, Any] = dict(req.options or {})
    if "num_predict" not in opts:
        opts["num_predict"] = settings.DEFAULT_NUM_PREDICT

    async def gen():
        # SSE 自动重连时间（毫秒）
        yield "retry: 3000\n\n"
        t0 = time.monotonic()
        try:
            async for chunk in ollama.generate_stream(
                req.prompt,
                model=req.model or settings.OLLAMA_MODEL,
                **opts,
            ):
                # SSE: 每条消息以 'data: ' 前缀，空行分隔
                for line in str(chunk).splitlines():
                    yield f"data: {line}\n\n"
        finally:
            LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="true").observe(
                max(time.monotonic() - t0, 0.0)
            )
        # 结束标记（可选）
        yield "data: [DONE]\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.post("/stream_raw")
async def chat_stream_raw(req: ChatRequest) -> StreamingResponse:
    opts: Dict[str, Any] = dict(req.options or {})
    if "num_predict" not in opts:
        opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
    async def gen():
        t0 = time.monotonic()
        try:
            async for line in ollama.generate_stream_raw(
                req.prompt,
                model=req.model or settings.OLLAMA_MODEL,
                **opts,
            ):
                yield line
        finally:
            LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="true").observe(
                max(time.monotonic() - t0, 0.0)
            )
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    # 与直连 Ollama 一致：逐行 JSON（JSON Lines）
    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8", headers=headers)


# -------- RAG (Retrieval Augmented Generation) --------

class RagChatRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    collection: Optional[str] = None
    model: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None


def _build_rag_prompt(query: str, contexts: List[str]) -> str:
    context_block = "\n\n".join(f"[DOC {i+1}] {c}" for i, c in enumerate(contexts))
    prompt = (
        "你是一个知识库问答助手。\n"
        "请仅依据提供的文档上下文来回答问题；\n"
        "如果文档中没有相关信息，请明确回答'未在文档中找到相关信息'，不要编造。\n\n"
        f"[文档上下文]\n{context_block}\n\n"
        f"[用户问题]\n{query}\n\n"
        "请用简洁中文回答。"
    )
    return prompt


def _prepare_contexts(
    scored: list,
    max_docs: int = 5,
    per_doc_max_chars: int = 500,
    total_max_chars: int = 2000,
):
    """From scored points, build deduplicated contexts and a sources list.

    Returns (contexts: List[str], sources: List[dict])
    """
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
        src = {"id": s.id, "score": s.score, "payload": pl}
        sources.append(src)
        if len(contexts) >= max_docs:
            break
    return contexts, sources


# -------- RAG 评估（批量查询统计） --------

class RagEvalRequest(BaseModel):
    queries: List[str]
    top_k: Optional[int] = None
    collection: Optional[str] = None
    model: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    export: Optional[str] = None  # 'csv' or 'json'


@router.post("/rag_eval")
async def rag_eval(req: RagEvalRequest):
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K
    if not qcli.collection_exists(coll):
        raise HTTPException(status_code=404, detail=f"collection not found: {coll}")

    # 批量嵌入（确保模型 + 指数退避重试，最终软失败返回空结果而非 500）
    emb_model = (req.model or getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL)
    await ollama.ensure_model(emb_model)
    t_emb = time.monotonic()
    vecs: List[List[float]] = []
    err_detail: Optional[str] = None
    max_attempts = 6
    delay = 0.5
    for attempt in range(1, max_attempts + 1):
        try:
            vecs = await ollama.embeddings(req.queries, model=emb_model)
            if vecs and len(vecs) == len(req.queries) and all(isinstance(v, list) and len(v) > 0 for v in vecs):
                err_detail = None
                break
            err_detail = "empty_or_mismatched_vectors"
        except Exception as e:
            err_detail = f"embed_exception: {type(e).__name__}: {e}"
        if attempt < max_attempts:
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, 8.0)
        else:
            break
    EMBED_SECONDS.labels(model=emb_model).observe(max(time.monotonic() - t_emb, 0.0))
    if err_detail is not None or not vecs or len(vecs) != len(req.queries):
        # 软失败：返回空结果，便于 CI gate 不中断；下游可据此判定失败
        details: List[Dict[str, Any]] = []
        summary = {
            "collection": coll,
            "total": len(req.queries),
            "hit_ratio": 0.0,
            "avg_top1": 0.0,
            "avg_mean_score": 0.0,
            "top_k": top_k,
            "error": err_detail or "failed_to_get_embeddings",
        }
        return {"summary": summary, "details": details}

    details: List[Dict[str, Any]] = []
    match_cnt = 0
    sum_top1 = 0.0
    sum_mean = 0.0
    n_with_results = 0

    for q, v in zip(req.queries, vecs):
        t_ret = time.monotonic()
        scored = qcli.search_vectors(coll, query=v, top_k=top_k, filters=req.filters)
        RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
        has = bool(scored)
        match_cnt += 1 if has else 0
        top1 = float(scored[0].score) if has else 0.0
        mean_score = float(sum(s.score for s in scored) / len(scored)) if has else 0.0
        if has:
            n_with_results += 1
            sum_top1 += top1
            sum_mean += mean_score
        details.append({
            "query": q,
            "has_match": has,
            "top1_score": top1,
            "mean_score": mean_score,
            "count": len(scored),
        })

    total = len(req.queries)
    summary = {
        "collection": coll,
        "total": total,
        "hit_ratio": (match_cnt / total) if total else 0.0,
        "avg_top1": (sum_top1 / n_with_results) if n_with_results else 0.0,
        "avg_mean_score": (sum_mean / n_with_results) if n_with_results else 0.0,
        "top_k": top_k,
    }

    if (req.export or "").lower() == "csv":
        # 生成 CSV 报告
        import io, csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["query", "has_match", "top1_score", "mean_score", "count"]) 
        for d in details:
            writer.writerow([d["query"], d["has_match"], f"{d['top1_score']:.6f}", f"{d['mean_score']:.6f}", d["count"]])
        # 在尾部追加汇总
        writer.writerow([])
        writer.writerow(["collection", "total", "hit_ratio", "avg_top1", "avg_mean_score", "top_k"]) 
        writer.writerow([summary["collection"], summary["total"], f"{summary['hit_ratio']:.6f}", f"{summary['avg_top1']:.6f}", f"{summary['avg_mean_score']:.6f}", summary["top_k"]])
        data = buf.getvalue()
        headers = {
            "Content-Disposition": "attachment; filename=rag_eval.csv",
            "Cache-Control": "no-cache",
        }
        return Response(content=data, media_type="text/csv; charset=utf-8", headers=headers)

    return {"summary": summary, "details": details}

@router.post("/rag")
async def chat_rag(req: RagChatRequest) -> Dict[str, Any]:
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K
    # embed query
    t_emb = time.monotonic()
    qvecs = await ollama.embeddings([req.query], model=req.model or settings.OLLAMA_MODEL)
    EMBED_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL)).observe(max(time.monotonic() - t_emb, 0.0))
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    # if collection is missing, return empty result
    if not qcli.collection_exists(coll):
        return {"collection": coll, "matches": [], "response": "未在文档中找到相关信息"}
    t_ret = time.monotonic()
    scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
    RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
    # pick contexts with dedup and limits, and collect sources
    contexts, sources = _prepare_contexts(scored)
    # build prompt
    prompt = _build_rag_prompt(req.query, contexts)
    # call LLM
    opts: Dict[str, Any] = dict(req.options or {})
    if "num_predict" not in opts:
        opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
    t_gen = time.monotonic()
    resp = await ollama.generate(
        prompt,
        model=req.model or settings.OLLAMA_MODEL,
        **opts,
    )
    LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="false").observe(max(time.monotonic() - t_gen, 0.0))
    RAG_MATCHES_TOTAL.labels(collection=coll, has_match=str(bool(scored)).lower()).inc()
    return {
        "collection": coll,
        "matches": [
            {"id": s.id, "score": s.score, "payload": getattr(s, "payload", None)} for s in scored
        ],
        "response": resp.get("response", ""),
        "sources": sources,
    }


@router.post("/rag_stream")
async def chat_rag_stream(req: RagChatRequest) -> StreamingResponse:
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K
    qvecs = await ollama.embeddings([req.query], model=req.model or settings.OLLAMA_MODEL)
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    if not qcli.collection_exists(coll):
        # 直接返回固定文本流
        async def empty_gen():
            yield "未在文档中找到相关信息"
        return StreamingResponse(empty_gen(), media_type="text/plain; charset=utf-8")
    t_ret = time.monotonic()
    scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
    RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
    contexts, sources = _prepare_contexts(scored)
    prompt = _build_rag_prompt(req.query, contexts)

    async def gen():
        opts: Dict[str, Any] = dict(req.options or {})
        if "num_predict" not in opts:
            opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
        t0 = time.monotonic()
        try:
            async for chunk in ollama.generate_stream(
                prompt,
                model=req.model or settings.OLLAMA_MODEL,
                **opts,
            ):
                yield chunk
        finally:
            LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="true").observe(
                max(time.monotonic() - t0, 0.0)
            )
        RAG_MATCHES_TOTAL.labels(collection=coll, has_match=str(bool(scored)).lower()).inc()
    async def tail_sources():
        # 在尾部追加参考来源
        yield "\n\n参考来源:\n"
        for src in sources:
            pl = src.get("payload") or {}
            tag = pl.get("tag") if isinstance(pl, dict) else None
            title = (pl.get("text") or "").strip() if isinstance(pl, dict) else ""
            title = title[:50] + ("..." if len(title) > 50 else "")
            line = f"- id={src['id']} score={round(src['score'],4)}"
            if tag:
                line += f" tag={tag}"
            if title:
                line += f" title={title}"
            yield line + "\n"

    async def merged_gen():
        yield "retry: 3000\n\n"
        async for chunk in gen():
            yield chunk
        async for line in tail_sources():
            yield line

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(merged_gen(), media_type="text/plain; charset=utf-8", headers=headers)


@router.post("/rag_stream_sse")
async def chat_rag_stream_sse(req: RagChatRequest) -> StreamingResponse:
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K
    t_emb = time.monotonic()
    qvecs = await ollama.embeddings([req.query], model=req.model or settings.OLLAMA_MODEL)
    EMBED_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL)).observe(max(time.monotonic() - t_emb, 0.0))
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    if not qcli.collection_exists(coll):
        async def empty_gen():
            yield "data: 未在文档中找到相关信息\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty_gen(), media_type="text/event-stream")
    t_ret = time.monotonic()
    scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
    RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
    contexts, sources = _prepare_contexts(scored)
    prompt = _build_rag_prompt(req.query, contexts)

    async def gen():
        opts: Dict[str, Any] = dict(req.options or {})
        if "num_predict" not in opts:
            opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
        t0 = time.monotonic()
        try:
            async for chunk in ollama.generate_stream(
                prompt,
                model=req.model or settings.OLLAMA_MODEL,
                **opts,
            ):
                yield chunk
        finally:
            LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="true").observe(
                max(time.monotonic() - t0, 0.0)
            )

    async def tail_sources_sse():
        yield "data: 参考来源:\n\n"
        for src in sources:
            pl = src.get("payload") or {}
            tag = pl.get("tag") if isinstance(pl, dict) else None
            title = (pl.get("text") or "").strip() if isinstance(pl, dict) else ""
            title = title[:50] + ("..." if len(title) > 50 else "")
            content = f"- id={src['id']} score={round(src['score'],4)}"
            if tag:
                content += f" tag={tag}"
            if title:
                content += f" title={title}"
            yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"

    async def merged_sse():
        yield "retry: 3000\n\n"
        async for chunk in gen():
            for line in str(chunk).splitlines():
                yield f"data: {line}\n\n"
        async for line in tail_sources_sse():
            yield line
        # 记录是否命中
        RAG_MATCHES_TOTAL.labels(collection=coll, has_match=str(bool(scored)).lower()).inc()

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(merged_sse(), media_type="text/event-stream", headers=headers)


@router.get("/stream_sse")
async def chat_stream_sse_get(prompt: str, model: Optional[str] = None, num_predict: Optional[int] = None) -> StreamingResponse:
    opts: Dict[str, Any] = {}
    opts["num_predict"] = num_predict or settings.DEFAULT_NUM_PREDICT

    async def gen():
        yield "retry: 3000\n\n"
        t0 = time.monotonic()
        try:
            async for chunk in ollama.generate_stream(
                prompt,
                model=model or settings.OLLAMA_MODEL,
                **opts,
            ):
                for line in str(chunk).splitlines():
                    yield f"data: {line}\n\n"
        finally:
            LLM_GENERATE_SECONDS.labels(model=(model or settings.OLLAMA_MODEL), stream="true").observe(
                max(time.monotonic() - t0, 0.0)
            )
        yield "data: [DONE]\n\n"




@router.get("/rag_stream_sse")
async def chat_rag_stream_sse_get(
    query: str,
    collection: Optional[str] = None,
    top_k: Optional[int] = None,
    model: Optional[str] = None,
    filters: Optional[str] = None,  # JSON string
) -> StreamingResponse:
    coll = collection or settings.QDRANT_COLLECTION
    k = top_k or settings.DEFAULT_TOP_K
    try:
        flt = json.loads(filters) if filters else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid filters json")

    t_emb = time.monotonic()
    qvecs = await ollama.embeddings([query], model=model or settings.OLLAMA_MODEL)
    EMBED_SECONDS.labels(model=(model or settings.OLLAMA_MODEL)).observe(max(time.monotonic() - t_emb, 0.0))
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    if not qcli.collection_exists(coll):
        async def empty_gen():
            yield "data: 未在文档中找到相关信息\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    t_ret = time.monotonic()
    scored = qcli.search_vectors(coll, query=qvecs[0], top_k=k, filters=flt)
    RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
    contexts, sources = _prepare_contexts(scored)
    prompt = _build_rag_prompt(query, contexts)

    async def gen():
        opts: Dict[str, Any] = {"num_predict": settings.DEFAULT_NUM_PREDICT}
        yield "retry: 3000\n\n"
        t0 = time.monotonic()
        try:
            async for chunk in ollama.generate_stream(
                prompt,
                model=model or settings.OLLAMA_MODEL,
                **opts,
            ):
                for line in str(chunk).splitlines():
                    yield f"data: {line}\n\n"
        finally:
            LLM_GENERATE_SECONDS.labels(model=(model or settings.OLLAMA_MODEL), stream="true").observe(
                max(time.monotonic() - t0, 0.0)
            )
        # 追加参考来源
        yield "data: 参考来源:\n\n"
        for src in sources:
            pl = src.get("payload") or {}
            tag = pl.get("tag") if isinstance(pl, dict) else None
            title = (pl.get("text") or "").strip() if isinstance(pl, dict) else ""
            title = title[:50] + ("..." if len(title) > 50 else "")
            content = f"- id={src['id']} score={round(src['score'],4)}"
            if tag:
                content += f" tag={tag}"
            if title:
                content += f" title={title}"
            yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"


# -------- RAG 预览（仅检索，不生成） --------

@router.post("/rag_preview")
async def rag_preview(req: RagChatRequest) -> Dict[str, Any]:
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K
    t_emb = time.monotonic()
    qvecs = await ollama.embeddings([req.query], model=req.model or settings.OLLAMA_MODEL)
    EMBED_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL)).observe(max(time.monotonic() - t_emb, 0.0))
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    if not qcli.collection_exists(coll):
        return {"collection": coll, "sources": []}
    t_ret = time.monotonic()
    scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
    RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
    _, sources = _prepare_contexts(scored)
    return {"collection": coll, "sources": sources}


@router.get("/rag_preview")
async def rag_preview_get(
    query: str,
    collection: Optional[str] = None,
    top_k: Optional[int] = None,
    model: Optional[str] = None,
    filters: Optional[str] = None,
) -> Dict[str, Any]:
    coll = collection or settings.QDRANT_COLLECTION
    k = top_k or settings.DEFAULT_TOP_K
    try:
        flt = json.loads(filters) if filters else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid filters json")
    t_emb = time.monotonic()
    qvecs = await ollama.embeddings([query], model=model or settings.OLLAMA_MODEL)
    EMBED_SECONDS.labels(model=(model or settings.OLLAMA_MODEL)).observe(max(time.monotonic() - t_emb, 0.0))
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    if not qcli.collection_exists(coll):
        return {"collection": coll, "sources": []}
    t_ret = time.monotonic()
    scored = qcli.search_vectors(coll, query=qvecs[0], top_k=k, filters=flt)
    RAG_RETRIEVAL_SECONDS.labels(collection=coll).observe(max(time.monotonic() - t_ret, 0.0))
    _, sources = _prepare_contexts(scored)
    return {"collection": coll, "sources": sources}

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
