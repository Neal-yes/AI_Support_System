from __future__ import annotations

import asyncio
import psycopg
from psycopg import AsyncConnection

from src.app.config import settings


def dsn() -> str:
    return (
        f"host={settings.POSTGRES_HOST} "
        f"port={settings.POSTGRES_PORT} "
        f"dbname={settings.POSTGRES_DB} "
        f"user={settings.POSTGRES_USER} "
        f"password={settings.POSTGRES_PASSWORD}"
    )


async def get_connection(timeout: float = 3.0) -> AsyncConnection:
    return await asyncio.wait_for(psycopg.AsyncConnection.connect(dsn()), timeout=timeout)
