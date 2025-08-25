from __future__ import annotations

from typing import Any, Dict, List, Optional
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
    ids: Optional[List[int]] = None
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
    vectors = await ollama.embeddings(req.texts, model=req.model or settings.OLLAMA_MODEL)
    dim = len(vectors[0]) if vectors and vectors[0] else 0
    return {"dimension": dim, "vectors": vectors}


@router.post("/upsert")
async def upsert(req: UpsertRequest) -> Dict[str, Any]:
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts is required")
    coll = req.collection or settings.QDRANT_COLLECTION
    vectors = await ollama.embeddings(req.texts, model=req.model or settings.OLLAMA_MODEL)
    if not vectors or not vectors[0]:
        raise HTTPException(status_code=500, detail="failed to get embeddings")
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
    qvecs = await ollama.embeddings([req.query], model=req.model or settings.OLLAMA_MODEL)
    if not qvecs or not qvecs[0]:
        raise HTTPException(status_code=500, detail="failed to get query embedding")
    # if collection is missing, return empty
    if not qcli.collection_exists(coll):
        return {"collection": coll, "matches": []}
    scored = qcli.search_vectors(coll, query=qvecs[0], top_k=top_k, filters=req.filters)
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
