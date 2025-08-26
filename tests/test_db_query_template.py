from __future__ import annotations

import pytest

from src.app.routers.db import validate_sql, wrap_with_limit, TEMPLATES


def test_validate_select_ok():
    sql = "SELECT id, name FROM users WHERE id = %(id)s"
    # should not raise
    validate_sql(sql)


def test_validate_reject_dml():
    bad = [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a=1",
        "DELETE FROM t",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN a int",
        "CREATE TABLE t(a int)",
    ]
    for sql in bad:
        with pytest.raises(ValueError):
            validate_sql(sql)


def test_validate_reject_comments_and_multi_stmt():
    # inline comment
    with pytest.raises(ValueError):
        validate_sql("SELECT 1 -- evil")
    # block comment
    with pytest.raises(ValueError):
        validate_sql("SELECT /* hack */ 1")
    # multi-statement via semicolon
    with pytest.raises(ValueError):
        validate_sql("SELECT 1; SELECT 2")


def test_wrap_with_limit():
    sql = "SELECT a FROM t"
    wrapped = wrap_with_limit(sql, 100)
    assert wrapped.strip().startswith("SELECT * FROM (")
    assert wrapped.strip().endswith("LIMIT 100")


def test_templates_have_echo_int():
    tpl = TEMPLATES.get("echo_int")
    assert tpl is not None
    assert "sql" in tpl and "max_rows" in tpl and "timeout_ms" in tpl
