import uuid

import pytest
import respx
from httpx import AsyncClient, ASGITransport, Response

from src.app.main import app


@pytest.mark.asyncio
@respx.mock
async def test_allow_hosts_permit_call():
    url = "https://example.com/ok"
    respx.get(url).mock(return_value=Response(200, text="OK"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "tenant_id": f"t-{uuid.uuid4()}",
            "tool_type": "http_get",
            "tool_name": "simple",
            "params": {"url": url},
            "options": {"allow_hosts": ["example.com"], "resp_max_chars": 100}
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["result"]["http"]["status_code"] == 200
        assert data["result"]["body"] == "OK"


@pytest.mark.asyncio
@respx.mock
async def test_allow_hosts_block_disallowed_host():
    # URL host not in allowlist should be blocked
    url = "https://not-allowed.example/"
    # no need to register respx mock; it shouldn't be called

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "tenant_id": f"t-{uuid.uuid4()}",
            "tool_type": "http_get",
            "tool_name": "simple",
            "params": {"url": url},
            "options": {"allow_hosts": ["example.com"]}
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 403
        assert "allow_hosts" in r.text


@pytest.mark.asyncio
@respx.mock
async def test_deny_hosts_block_call():
    url = "https://blocked.example/path"
    # no respx mock; should be blocked before network

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "tenant_id": f"t-{uuid.uuid4()}",
            "tool_type": "http_get",
            "tool_name": "simple",
            "params": {"url": url},
            "options": {"deny_hosts": ["blocked.example"]}
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 403
        assert "deny_hosts" in r.text
