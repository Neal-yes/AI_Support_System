import asyncio
import uuid

import pytest
import respx
from fastapi import HTTPException
from httpx import Response

from src.app.core.tool_executor import executor


@pytest.mark.asyncio
@respx.mock
async def test_cache_hit_http_get():
    # Mock HTTP GET
    url = "https://example.com/"
    respx.get(url).mock(return_value=Response(200, text="OK"))

    tenant = f"t-{uuid.uuid4()}"
    tool_type = "http_get"
    tool_name = "cache_demo"
    params = {"url": url}
    options = {"timeout_ms": 1000, "cache_ttl_ms": 60000}

    r1 = await executor.execute(tenant, tool_type, tool_name, params, options)
    assert r1["http"]["status_code"] == 200
    assert r1.get("from_cache") is False

    # Second call should hit cache
    r2 = await executor.execute(tenant, tool_type, tool_name, params, options)
    assert r2.get("from_cache") is True
    assert "body" in r2


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_triggered():
    # Mock HTTP GET to be fast
    url = "https://example.org/"
    respx.get(url).mock(return_value=Response(200, text="OK"))

    tenant = f"t-{uuid.uuid4()}"
    tool_type = "http_get"
    tool_name = "rl_demo"
    params = {"url": url}
    options = {"timeout_ms": 1000, "rate_limit_per_sec": 1}

    # First call passes
    r1 = await executor.execute(tenant, tool_type, tool_name, params, options)
    assert r1["http"]["status_code"] == 200

    # Second call within same second should raise 429
    with pytest.raises(HTTPException) as ei:
        await executor.execute(tenant, tool_type, tool_name, params, options)
    assert ei.value.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_http_post_json_success():
    url = "https://api.example.com/echo"
    respx.post(url).mock(return_value=Response(200, json={"ok": True}))

    tenant = f"t-{uuid.uuid4()}"
    tool_type = "http_post"
    tool_name = "simple"
    params = {"url": url, "body": {"a": 1}}
    options = {"timeout_ms": 2000, "content_type": "application/json"}

    r = await executor.execute(tenant, tool_type, tool_name, params, options)
    assert r["http"]["status_code"] == 200
    assert r["http"]["ok"] is True
    assert "body" in r


@pytest.mark.asyncio
@respx.mock
async def test_http_post_text_plain_success():
    url = "https://api.example.com/echo-text"
    respx.post(url).mock(return_value=Response(200, text="pong"))

    tenant = f"t-{uuid.uuid4()}"
    tool_type = "http_post"
    tool_name = "simple"
    params = {"url": url, "body": "ping"}
    options = {"timeout_ms": 2000, "content_type": "text/plain"}

    r = await executor.execute(tenant, tool_type, tool_name, params, options)
    assert r["http"]["status_code"] == 200
    assert r["http"]["ok"] is True
    assert r.get("body") == "pong"


@pytest.mark.asyncio
@respx.mock
async def test_http_post_retry_then_fail_with_simulate():
    # 使用 simulate_fail 触发内部异常，测试重试与最终 502
    url = "https://api.example.com/will-not-call"
    # 即便没有真正发起请求，也提供一个默认 mock，避免 httpx 抱怨未匹配
    respx.post(url).mock(return_value=Response(500, text="err"))

    tenant = f"t-{uuid.uuid4()}"
    tool_type = "http_post"
    tool_name = "simple"
    params = {"url": url, "body": {"x": 1}}
    options = {"timeout_ms": 100, "retry_max": 1, "retry_backoff_ms": 10, "simulate_fail": True}

    with pytest.raises(HTTPException) as ei:
        await executor.execute(tenant, tool_type, tool_name, params, options)
    assert ei.value.status_code == 502


@pytest.mark.asyncio
async def test_http_post_invalid_url_400():
    tenant = f"t-{uuid.uuid4()}"
    tool_type = "http_post"
    tool_name = "simple"
    params = {"url": "ftp://invalid", "body": {"a": 1}}
    options = {"timeout_ms": 2000}

    with pytest.raises(HTTPException) as ei:
        await executor.execute(tenant, tool_type, tool_name, params, options)
    assert ei.value.status_code == 400
