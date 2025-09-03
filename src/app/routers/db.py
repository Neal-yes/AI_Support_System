from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from src.app.clients.postgres import get_connection
from psycopg.rows import dict_row
from src.app.core.metrics import DB_QUERY_SECONDS, DB_QUERY_TOTAL
from src.app.config import settings

router = APIRouter(prefix="/api/v1/db", tags=["db"])

logger = logging.getLogger(__name__)

# ---- Templates (built-in) ----
# NOTE: Only SELECT statements are allowed; parameters must be named (psycopg style: %(name)s)
# Primary shape is FLAT for compatibility with tests: {template_id: {sql,max_rows,timeout_ms}}
# Router supports both flat and versioned: {template_id: {version: {sql,max_rows,timeout_ms}}}
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "echo_int": {
        "sql": "SELECT %(x)s::int AS x",
        "max_rows": 1000,
        "timeout_ms": 3000,
    }
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
    template_version: Optional[str] = Field(None, description="Optional explicit template version (e.g., v1)")
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
    tpl_entry = TEMPLATES.get(payload.template_id)
    tenant = x_tenant_id or "default"
    if not tpl_entry:
        DB_QUERY_TOTAL.labels(template=payload.template_id, tenant=tenant, result="rejected").inc()
        raise ValueError("unknown template_id")

    # Normalize to versioned dict for internal logic
    if "sql" in tpl_entry:
        # flat shape -> synthesize single version
        tpl_versions: Dict[str, Dict[str, Any]] = {"v1": tpl_entry}
    else:
        # already versioned
        tpl_versions = tpl_entry  # type: ignore[assignment]

    # resolve version (explicit or latest by lexical order)
    version_keys = sorted(list(tpl_versions.keys()))
    selected_version = payload.template_version if (payload.template_version and payload.template_version in tpl_versions) else (version_keys[-1] if version_keys else None)
    if not selected_version:
        DB_QUERY_TOTAL.labels(template=payload.template_id, tenant=tenant, result="rejected").inc()
        raise ValueError("no available template version")

    tpl = tpl_versions[selected_version]
    sql = str(tpl.get("sql", ""))
    max_rows = int(tpl.get("max_rows", 1000))
    timeout_ms = int(tpl.get("timeout_ms", 3000))
    version = str(selected_version)

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

    # audit log (in-process)
    try:
        logger.info(
            "db_template_query",
            extra={
                "event": "db_template_query",
                "tenant": tenant,
                "template_id": payload.template_id,
                "template_version": version,
                "explain": bool(payload.explain),
                "row_count": len(rows),
            },
        )
    except Exception:
        pass

    return DBTemplateResponse(
        template_id=payload.template_id,
        template_version=version,
        row_count=len(rows),
        rows=rows,
        request_id=None,
    )


@router.get("/templates")
async def list_templates() -> Dict[str, List[str]]:
    """List available template ids and their versions."""
    out: Dict[str, List[str]] = {}
    for tid, entry in TEMPLATES.items():
        if isinstance(entry, dict) and "sql" in entry:
            out[tid] = ["v1"]
        else:
            out[tid] = sorted(list(entry.keys()))  # type: ignore[arg-type]
    return out


_AUDIT_RING: List[Dict[str, Any]] = []
_AUDIT_MAX = 200


def _audit_push(entry: Dict[str, Any]) -> None:
    try:
        _AUDIT_RING.append({**entry, "ts": time.time()})
        if len(_AUDIT_RING) > _AUDIT_MAX:
            del _AUDIT_RING[: len(_AUDIT_RING) - _AUDIT_MAX]
    except Exception:
        pass


@router.get("/audit")
async def list_audit(limit: int = Query(default=50, ge=1, le=200)) -> List[Dict[str, Any]]:
    """Return recent db template query audit entries (best-effort)."""
    try:
        return list(_AUDIT_RING[-limit:])
    except Exception:
        return []
