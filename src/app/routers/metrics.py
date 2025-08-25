from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(prefix="", tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    data = generate_latest()  # bytes
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
