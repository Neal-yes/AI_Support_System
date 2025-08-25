from __future__ import annotations

from typing import List, Optional, Any, Dict, Union
from uuid import uuid4
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from src.app.config import settings


def get_client() -> QdrantClient:
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)


def ensure_collection(collection_name: str, vector_size: int, distance: qmodels.Distance = qmodels.Distance.COSINE) -> None:
    """Ensure a Qdrant collection exists with the desired vector size.

    If the collection exists but its vector size mismatches, drop and recreate to avoid
    runtime errors like "Vector dimension error: expected dim: X, got Y".
    Supports both single-vector and named-vector configurations.
    """
    client = get_client()
    if not collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
        )
        return

    # Collection exists: check its current vector size
    try:
        info = client.get_collection(collection_name=collection_name)
        existing_size = None
        # Try to navigate common schema layouts
        vectors_cfg = None
        # qdrant >=1.6: info.config.params.vectors
        vectors_cfg = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
        if vectors_cfg is None:
            # Fallback older or different SDK shapes
            vectors_cfg = getattr(info, "vectors", None)

        if isinstance(vectors_cfg, qmodels.VectorParams):
            existing_size = getattr(vectors_cfg, "size", None)
        elif isinstance(vectors_cfg, dict):
            # Named vectors mapping: pick the first entry's size
            try:
                first = next(iter(vectors_cfg.values()))
                existing_size = getattr(first, "size", None)
            except Exception:
                existing_size = None
        # If still unknown, try dict() conversion
        if existing_size is None:
            try:
                as_dict = info.model_dump() if hasattr(info, "model_dump") else info.dict()  # type: ignore[assignment]
                params = as_dict.get("config", {}).get("params", {})
                vecs = params.get("vectors") or as_dict.get("vectors")
                if isinstance(vecs, dict):
                    first = next(iter(vecs.values()))
                    existing_size = int(first.get("size")) if isinstance(first, dict) else None
                elif isinstance(vecs, dict) is False and vecs is not None:
                    existing_size = int(getattr(vecs, "size", None))
            except Exception:
                existing_size = None

        if existing_size is not None and int(existing_size) != int(vector_size):
            # Recreate with the correct size
            client.delete_collection(collection_name=collection_name)
            client.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
            )
    except Exception:
        # If we fail to introspect, attempt to use the collection as-is
        # Better fail later with a clear server error than crash here.
        pass


def collection_exists(collection_name: str) -> bool:
    client = get_client()
    try:
        _ = client.get_collection(collection_name)
        return True
    except Exception:
        return False


def upsert_vectors(collection_name: str, vectors: List[List[float]], payloads: Optional[List[Dict[str, Any]]] = None, ids: Optional[List[Union[str, int]]] = None) -> None:
    client = get_client()
    points = []
    for i, vec in enumerate(vectors):
        pid = ids[i] if ids and i < len(ids) else str(uuid4())
        pl = payloads[i] if payloads and i < len(payloads) else None
        points.append(qmodels.PointStruct(id=pid, vector=vec, payload=pl))
    client.upsert(collection_name=collection_name, points=points, wait=True)


def _build_filter(filters: Optional[Dict[str, Any]]) -> Optional[qmodels.Filter]:
    if not filters:
        return None
    must: List[qmodels.FieldCondition] = []
    for k, v in filters.items():
        must.append(qmodels.FieldCondition(key=str(k), match=qmodels.MatchValue(value=v)))
    return qmodels.Filter(must=must)


def search_vectors(collection_name: str, query: List[float], top_k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[qmodels.ScoredPoint]:
    client = get_client()
    qf = _build_filter(filters)
    return client.search(collection_name=collection_name, query_vector=query, limit=top_k, query_filter=qf)


# -------- Collection & Points Management --------

def list_collections() -> List[str]:
    client = get_client()
    cols = client.get_collections()
    # cols.collections: List[CollectionDescription]
    return [c.name for c in getattr(cols, "collections", [])]


def delete_collection(collection_name: str) -> None:
    client = get_client()
    client.delete_collection(collection_name=collection_name)


def clear_collection(collection_name: str) -> None:
    """Delete all points in a collection (keep schema) by scrolling IDs in batches.

    This avoids relying on server/SDK support for AllSelector and works across versions.
    """
    client = get_client()
    next_page: Optional[qmodels.ScrollOffset] = None
    while True:
        resp = client.scroll(
            collection_name=collection_name,
            limit=1000,
            with_vectors=False,
            with_payload=False,
            offset=next_page,
        )
        points, next_page = resp
        if not points:
            break
        ids = [p.id for p in points]
        if ids:
            client.delete(collection_name=collection_name, points_selector=qmodels.PointIdsList(points=ids), wait=True)


def delete_points_by_ids(collection_name: str, ids: List[Union[str, int]]) -> int:
    client = get_client()
    client.delete(collection_name=collection_name, points_selector=qmodels.PointIdsList(points=ids), wait=True)
    return len(ids)


def delete_points_by_filter(collection_name: str, filters: Dict[str, Any]) -> int:
    """Delete by filter and return affected count.

    Use Qdrant count API to get affected rows, then perform delete with FilterSelector.
    This avoids potential infinite loops or long scans with scroll.
    """
    client = get_client()
    flt = _build_filter(filters)
    # count via count API (exact)
    try:
        cnt = client.count(collection_name=collection_name, count_filter=flt, exact=True)
        total = int(getattr(cnt, "count", 0))
    except Exception:
        total = 0
    # perform delete
    client.delete(collection_name=collection_name, points_selector=qmodels.FilterSelector(filter=flt), wait=True)
    return total


def get_collection_info(collection_name: str) -> Dict[str, Any]:
    client = get_client()
    info = client.get_collection(collection_name=collection_name)
    # pydantic model -> dict
    try:
        return info.model_dump()  # type: ignore[attr-defined]
    except Exception:
        try:
            return info.dict()  # fallback older pydantic style
        except Exception:
            return {"raw": str(info)}
