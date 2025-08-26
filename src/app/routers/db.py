from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from src.app.clients.postgres import get_connection
from psycopg.rows import dict_row
from src.app.core.metrics import DB_QUERY_SECONDS, DB_QUERY_TOTAL
from src.app.config import settings

router = APIRouter(prefix="/api/v1/db", tags=["db"])

# ---- Templates (minimal, built-in for now) ----
# NOTE: Only SELECT statements are allowed; parameters must be named (psycopg style: %(name)s)
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "echo_int": {
        "sql": "SELECT %(x)s::int AS x",
        "max_rows": 1000,
        "timeout_ms": 3000,
        "version": "v1",
    },
}

FORBIDDEN_PATTERN = re.compile(
    r";|--|/\*|\*/|\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|GRANT|REVOKE|TRUNCATE|MERGE|CALL|DO)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> None:
    s = sql.strip()
    # must start with SELECT
    if not re.match(r"^SELECT\b", s, re.IGNORECASE):
        raise ValueError("only SELECT is allowed")
    # reject forbidden tokens/comments/multiple statements
    if FORBIDDEN_PATTERN.search(s):
        raise ValueError("forbidden statement or comment detected")


def wrap_with_limit(sql: str, max_rows: int) -> str:
    # Wrap to enforce limit without altering original semantics
    return f"SELECT * FROM ( {sql} ) __t__ LIMIT {int(max_rows)}"


class DBTemplateRequest(BaseModel):
    template_id: str = Field(..., description="Registered template id")
    params: Dict[str, Any] = Field(default_factory=dict)
    explain: Optional[bool] = False


class DBTemplateResponse(BaseModel):
    template_id: str
    template_version: str
    row_count: int
    rows: List[Dict[str, Any]]
    request_id: Optional[str] = None


@router.post("/query_template", response_model=DBTemplateResponse)
async def query_template(
    payload: DBTemplateRequest,
    x_tenant_id: Optional[str] = Header(default="", alias=settings.HEADER_TENANT_KEY),
):
    tpl = TEMPLATES.get(payload.template_id)
    tenant = x_tenant_id or "default"
    if not tpl:
        DB_QUERY_TOTAL.labels(template=payload.template_id, tenant=tenant, result="rejected").inc()
        raise ValueError("unknown template_id")

    sql = str(tpl.get("sql", ""))
    max_rows = int(tpl.get("max_rows", 1000))
    timeout_ms = int(tpl.get("timeout_ms", 3000))
    version = str(tpl.get("version", "v1"))

    # Validation
    try:
        validate_sql(sql)
    except Exception:
        DB_QUERY_TOTAL.labels(template=payload.template_id, tenant=tenant, result="rejected").inc()
        raise

    # Prepare SQL (explain or limited)
    final_sql = f"EXPLAIN (ANALYZE false, FORMAT TEXT) {sql}" if payload.explain else wrap_with_limit(sql, max_rows)

    started = time.perf_counter()
    try:
        # NOTE: rely on psycopg3 async connection; not executing in tests when no DB available
        async with await get_connection(timeout=timeout_ms / 1000.0) as conn:
            # dict row factory
            async with conn.cursor(row_factory=dict_row) as cur:
                await asyncio.wait_for(cur.execute(final_sql, payload.params), timeout=timeout_ms / 1000.0)
                rows = [dict(r) for r in await cur.fetchall()]
        DB_QUERY_TOTAL.labels(template=payload.template_id, tenant=tenant, result="ok").inc()
    except asyncio.TimeoutError:
        DB_QUERY_TOTAL.labels(template=payload.template_id, tenant=tenant, result="timeout").inc()
        raise
    except Exception:
        DB_QUERY_TOTAL.labels(template=payload.template_id, tenant=tenant, result="error").inc()
        raise
    finally:
        DB_QUERY_SECONDS.labels(template=payload.template_id, tenant=tenant).observe(time.perf_counter() - started)

    return DBTemplateResponse(
        template_id=payload.template_id,
        template_version=version,
        row_count=len(rows),
        rows=rows,
        request_id=None,
    )
