import uuid

import pytest
import respx
from httpx import AsyncClient, ASGITransport, Response

from src.app.main import app


@pytest.mark.asyncio
@respx.mock
async def test_policy_merge_applies_for_http_get_resp_max_chars():
    # According to configs/tools_policies.json:
    # - default.options.resp_max_chars = 2048
    # - tenants.default.tools.http_get.names.simple.options.resp_max_chars = 4096
    # Expect merged resp_max_chars = 4096 when tenant=default, tool_type=http_get, tool_name=simple
    url = "https://example.com/large"
    large_text = "A" * 10000
    respx.get(url).mock(return_value=Response(200, text=large_text))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "tenant_id": "default",
            "tool_type": "http_get",
            "tool_name": "simple",
            "params": {"url": url},
            # no options provided; rely on policies
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["result"]["http"]["status_code"] == 200
        # Body should be truncated to 4096 by merged policies
        assert "body" in data["result"]
        assert isinstance(data["result"]["body"], str)
        assert len(data["result"]["body"]) == 4096


@pytest.mark.asyncio
@respx.mock
async def test_request_options_override_policies_for_resp_max_chars():
    # Request-level options should override policy to 1000
    url = "https://example.com/large2"
    large_text = "B" * 5000
    respx.get(url).mock(return_value=Response(200, text=large_text))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tenant = f"t-{uuid.uuid4()}"
        payload = {
            "tenant_id": tenant,
            "tool_type": "http_get",
            "tool_name": "simple",
            "params": {"url": url},
            "options": {"resp_max_chars": 1000}
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["result"]["http"]["status_code"] == 200
        assert "body" in data["result"]
        assert len(data["result"]["body"]) == 1000
