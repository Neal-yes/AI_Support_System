from __future__ import annotations

from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, HTTPException, Request
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
        return query
    ctx = "\n\n".join(f"[DOC {i+1}] {c}" for i, c in enumerate(contexts))
    return (
        "你是一个知识库问答助手。\n"
        "请仅依据提供的文档上下文来回答问题；\n"
        "如果文档中没有相关信息，请明确回答'未在文档中找到相关信息'，不要编造。\n\n"
        f"[文档上下文]\n{ctx}\n\n"
        f"[用户问题]\n{query}\n\n"
        "请用简洁中文回答。"
    )


def _prepare_contexts(scored: list, max_docs: int = 5, per_doc_max_chars: int = 500, total_max_chars: int = 2000):
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


@router.post("/ask")
async def ask(req: AskRequest, request: Request) -> Dict[str, Any]:
    tenant = getattr(request.state, "tenant", "_anon_")
    request_id = getattr(request.state, "request_id", "")

    # Plain LLM path
    if not req.use_rag:
        opts: Dict[str, Any] = dict(req.options or {})
        if "num_predict" not in opts:
            opts["num_predict"] = settings.DEFAULT_NUM_PREDICT
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
            raise HTTPException(status_code=500, detail=f"plain generation failed: {e}")
        LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="false").observe(max(time.monotonic() - t0, 0.0))
        return {
            "response": resp.get("response", ""),
            "sources": [],
            "meta": {"tenant": tenant, "request_id": request_id, "use_rag": False},
        }

    # RAG path
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K

    # embed query
    t_emb = time.monotonic()
    qvecs = await ollama.embeddings([req.query], model=req.model or settings.OLLAMA_MODEL)
    EMBED_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL)).observe(max(time.monotonic() - t_emb, 0.0))
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
    try:
        t_gen = time.monotonic()
        resp = await ollama.generate(
            prompt,
            model=req.model or settings.OLLAMA_MODEL,
            **opts,
        )
        LLM_GENERATE_SECONDS.labels(model=(req.model or settings.OLLAMA_MODEL), stream="false").observe(max(time.monotonic() - t_gen, 0.0))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"rag generation failed: {e}")

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
