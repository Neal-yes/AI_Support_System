from __future__ import annotations

import redis.asyncio as aioredis
from src.app.config import settings


def get_client() -> aioredis.Redis:
    return aioredis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
