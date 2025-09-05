from __future__ import annotations

import asyncio
from typing import Any, Dict

import httpx
import redis.asyncio as aioredis
import psycopg
from fastapi import APIRouter

from src.app.config import settings, ServiceStatus
from src.app.clients import ollama

router = APIRouter(prefix="", tags=["health"])


async def check_postgres(timeout: float = 2.0) -> ServiceStatus:
    dsn = (
        f"host={settings.POSTGRES_HOST} "
        f"port={settings.POSTGRES_PORT} "
        f"dbname={settings.POSTGRES_DB} "
        f"user={settings.POSTGRES_USER} "
        f"password={settings.POSTGRES_PASSWORD}"
    )
    try:
        async with await asyncio.wait_for(psycopg.AsyncConnection.connect(dsn), timeout=timeout) as conn:
            async with conn.cursor() as cur:
                await asyncio.wait_for(cur.execute("SELECT 1"), timeout=timeout)
                _ = await asyncio.wait_for(cur.fetchone(), timeout=timeout)
        return ServiceStatus(healthy=True)
    except Exception as e:
        return ServiceStatus(healthy=False, detail=str(e))


async def check_redis(timeout: float = 1.5) -> ServiceStatus:
    try:
        client = aioredis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
        pong = await asyncio.wait_for(client.ping(), timeout=timeout)
        await client.close()
        return ServiceStatus(healthy=bool(pong))
    except Exception as e:
        return ServiceStatus(healthy=False, detail=str(e))


async def check_qdrant(timeout: float = 2.0) -> ServiceStatus:
    url = f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/readyz"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return ServiceStatus(healthy=resp.status_code == 200, detail=str(resp.text) if resp.status_code != 200 else None)
    except Exception as e:
        return ServiceStatus(healthy=False, detail=str(e))


async def check_ollama(timeout: float = 2.0) -> ServiceStatus:
    url = f"http://{settings.OLLAMA_HOST}:{settings.OLLAMA_PORT}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return ServiceStatus(healthy=resp.status_code == 200, detail=str(resp.text) if resp.status_code != 200 else None)
    except Exception as e:
        return ServiceStatus(healthy=False, detail=str(e))


@router.get("/health")
async def health() -> Dict[str, Any]:
    results = await asyncio.gather(
        check_postgres(),
        check_redis(),
        check_qdrant(),
        check_ollama(),
        return_exceptions=False,
    )
    postgres, redis_status, qdrant, ollama = results
    overall = all([postgres.healthy, redis_status.healthy, qdrant.healthy, ollama.healthy])
    return {
        "status": "ok" if overall else "degraded",
        "api_port": settings.API_PORT,
        "services": {
            "postgres": postgres.model_dump(),
            "redis": redis_status.model_dump(),
            "qdrant": qdrant.model_dump(),
            "ollama": ollama.model_dump(),
        },
    }


@router.get("/healthz")
async def healthz() -> Dict[str, Any]:
    """K8s/LB 兼容健康检查简化版，仅返回总体状态。"""
    results = await asyncio.gather(
        check_postgres(),
        check_redis(),
        check_qdrant(),
        check_ollama(),
        return_exceptions=False,
    )
    postgres, redis_status, qdrant, ollama = results
    overall = all([postgres.healthy, redis_status.healthy, qdrant.healthy, ollama.healthy])
    return {"status": "ok" if overall else "degraded"}


@router.get("/-/live")
async def live() -> Dict[str, Any]:
    """存活探针：不做外部依赖检查，返回 200 即视为存活。"""
    return {"status": "ok"}


@router.get("/-/ready")
async def ready() -> Dict[str, Any]:
    """就绪探针：仅检查关键依赖（Qdrant 与 Ollama），更快、更稳定。"""
    results = await asyncio.gather(
        check_qdrant(),
        check_ollama(),
        return_exceptions=False,
    )
    qdrant, ollama_status = results
    # 进行一次轻量 Embeddings 探测，确保模型真正可用
    try:
        vecs = await asyncio.wait_for(ollama.embeddings(["ready"], timeout=15), timeout=20)
        emb_ok = bool(vecs and vecs[0])
        embed_status = ServiceStatus(healthy=emb_ok)
    except Exception as e:
        embed_status = ServiceStatus(healthy=False, detail=str(e))
    overall = all([qdrant.healthy, ollama_status.healthy, embed_status.healthy])
    return {
        "status": "ok" if overall else "degraded",
        "services": {
            "qdrant": qdrant.model_dump(),
            "ollama": ollama_status.model_dump(),
            "ollama_embed": embed_status.model_dump(),
        },
    }
