from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.app.clients import ollama
from src.app.clients import qdrant as qcli
from src.app.config import settings

router = APIRouter(prefix="/embedding", tags=["embedding"])


class EmbedRequest(BaseModel):
    texts: List[str]
    model: Optional[str] = None


class UpsertRequest(BaseModel):
    texts: List[str]
    payloads: Optional[List[Dict[str, Any]]] = None
    ids: Optional[List[Union[int, str]]] = None
    collection: Optional[str] = None
    model: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = None
    collection: Optional[str] = None
    model: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None


@router.post("/embed")
async def embed(req: EmbedRequest) -> Dict[str, Any]:
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts is required")
    # 优先使用专用嵌入模型；仅当显式传入 model 时才覆盖
    chosen_model = (req.model or getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL)
    vectors = await ollama.embeddings(req.texts, model=chosen_model)
    dim = len(vectors[0]) if vectors and vectors[0] else 0
    return {"dimension": dim, "vectors": vectors}


@router.post("/upsert")
async def upsert(req: UpsertRequest) -> Dict[str, Any]:
    """
    向量入库（支持按自定义 ID 覆盖）

    - ids 支持 `int` 或 `str`（例如字符串 UUID）。
    - 若不提供 ids，服务会按 Qdrant 默认策略生成 ID。
    - 若 422 报错指向 `ids[0]` 需要整数，说明后端仍是旧类型定义，请确认：
      `UpsertRequest.ids: Optional[List[Union[int, str]]] = None` 并重启 API。

    请求体字段：
    - texts: List[str] 必填
    - payloads: List[Dict] 可选；未提供时会自动生成 `{ "text": 原文 }`
    - ids: List[int|str] 可选；传入可覆盖既有点位
    - collection/model: 可选
    """
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts is required")
    coll = req.collection or settings.QDRANT_COLLECTION
    # 使用专用嵌入模型，除非显式指定
    chosen_model = (req.model or getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL)
    # 先确保模型可用，并在冷启动阶段对嵌入调用进行重试以避免瞬时 500
    max_attempts = 6
    delay = 0.5
    last_err: Optional[Exception] = None
    vectors: List[List[float]] = []
    for attempt in range(1, max_attempts + 1):
        try:
            # best-effort 确保模型拉取完成
            try:
                _ = await ollama.ensure_model(chosen_model, timeout=90)
            except Exception:
                # ensure_model 失败不致命，继续尝试 embeddings（由下方重试兜底）
                pass
            vectors = await ollama.embeddings(req.texts, model=chosen_model)
            if vectors and vectors[0]:
                break
            raise RuntimeError("empty embeddings")
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                await asyncio.sleep(delay)
                delay = min(delay * 1.8, 8.0)
            else:
                raise HTTPException(status_code=500, detail=f"embedding failed after retries: {type(e).__name__}: {e}")
    dim = len(vectors[0])
    # ensure collection exists
    qcli.ensure_collection(coll, vector_size=dim)
    # auto-augment payloads with text if not provided
    payloads = req.payloads or [ {"text": t} for t in req.texts ]
    qcli.upsert_vectors(coll, vectors=vectors, payloads=payloads, ids=req.ids)
    return {"collection": coll, "dimension": dim, "count": len(vectors)}


@router.post("/search")
async def search(req: SearchRequest) -> Dict[str, Any]:
    coll = req.collection or settings.QDRANT_COLLECTION
    top_k = req.top_k or settings.DEFAULT_TOP_K
    # embed query
    chosen_model = (req.model or getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL)
    qvecs = await ollama.embeddings([req.query], model=chosen_model)
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    dim = len(qvecs[0])
    # If collection exists, validate expected vector dimension to avoid opaque 400 from Qdrant
    if qcli.collection_exists(coll):
        try:
            info = qcli.get_collection_info(coll)
            # best-effort extract size
            expected = (
                info.get("config", {}).get("params", {}).get("vectors", {}).get("size")
                or info.get("params", {}).get("vectors", {}).get("size")
                or info.get("params", {}).get("size")
                or (info.get("vectors", {}) if isinstance(info.get("vectors", {}), dict) else {}).get("size")
                or 0
            )
            expected = int(expected or 0)
            if expected and expected != dim:
                raise HTTPException(status_code=400, detail=f"vector dimension mismatch: collection expects {expected}, query has {dim}")
        except HTTPException:
            raise
        except Exception:
            # proceed; server-side Qdrant may still return detailed error
            pass
    # if collection is missing, return empty
    if not qcli.collection_exists(coll):
        return {"collection": coll, "matches": []}
    try:
        scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
    except Exception as e:
        # Surface upstream errors as 400 for easier client debugging
        raise HTTPException(status_code=400, detail=f"qdrant search failed: {e}")
    # serialize
    matches = [
        {
            "id": s.id,
            "score": s.score,
            "payload": getattr(s, "payload", None),
        }
        for s in scored
    ]
    return {"collection": coll, "matches": matches}
