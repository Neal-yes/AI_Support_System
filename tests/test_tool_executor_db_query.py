from __future__ import annotations

import pytest
from fastapi import HTTPException
import pytest

from src.app.core.tool_executor import ToolExecutor


def test_db_query_validate_ok_via_internal():
    ex = ToolExecutor()
    norm = ex._validate_db_query(
        params={
            "template_id": "tpl1",
            "params": {"x": 1},
            "explain": False,
        },
        options={"timeout_ms": 500, "max_rows": 100},
    )
    assert norm["template_id"] == "tpl1"
    assert norm["explain"] is False
    assert norm["max_rows"] == 100


def test_db_query_validate_bad_timeout():
    ex = ToolExecutor()
    with pytest.raises(HTTPException):
        ex._validate_db_query(params={"template_id": "a", "params": {}}, options={"timeout_ms": 50})


@pytest.mark.asyncio
async def test_db_query_execute_path_not_reached_with_simulate_fail():
    # ensure that execute doesn't touch DB when simulate_fail is True
    ex = ToolExecutor()
    with pytest.raises(HTTPException) as ei:
        await ex.execute(
            tenant_id="demo",
            tool_type="db_query",
            tool_name="template",
            params={
                "template_id": "tpl1",
                "params": {"x": 1},
                # provide a sql to pass later validation if it were reached
                "sql": "SELECT 1",
            },
            options={"timeout_ms": 500, "simulate_fail": True},
        )
    # 502 means failed before any DB work (simulated failure path)
    assert isinstance(ei.value, HTTPException)
    assert ei.value.status_code == 502
