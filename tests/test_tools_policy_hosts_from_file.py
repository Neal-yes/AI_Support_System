import json
import shutil
from pathlib import Path

import pytest
import respx
from httpx import AsyncClient, ASGITransport, Response

from src.app.main import app
from src.app.routers import tools as tools_router


@pytest.mark.asyncio
@respx.mock
async def test_policy_allow_hosts_allows_call():
    policy_path = Path("configs/tools_policies.json")
    assert policy_path.exists(), "tools_policies.json must exist for this test"
    backup_path = policy_path.with_suffix(".json.bak")
    shutil.copyfile(policy_path, backup_path)
    try:
        base = json.loads(policy_path.read_text(encoding="utf-8"))
        # Inject allow_hosts for default tenant http_get.simple
        base.setdefault("tenants", {}).setdefault("default", {}).setdefault("tools", {}).setdefault("http_get", {}).setdefault("names", {}).setdefault("simple", {}).setdefault("options", {})["allow_hosts"] = ["example.com"]
        policy_path.write_text(json.dumps(base), encoding="utf-8")
        tools_router._load_policies(force=True)

        url = "https://example.com/ok"
        respx.get(url).mock(return_value=Response(200, text="OK"))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "tenant_id": "default",
                "tool_type": "http_get",
                "tool_name": "simple",
                "params": {"url": url},
            }
            r = await client.post("/api/v1/tools/invoke", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["result"]["http"]["status_code"] == 200
            assert data["result"]["body"] == "OK"
    finally:
        shutil.copyfile(backup_path, policy_path)
        tools_router._load_policies(force=True)
        backup_path.unlink(missing_ok=True)


@pytest.mark.asyncio
@respx.mock
async def test_policy_deny_hosts_blocks_call():
    policy_path = Path("configs/tools_policies.json")
    assert policy_path.exists(), "tools_policies.json must exist for this test"
    backup_path = policy_path.with_suffix(".json.bak")
    shutil.copyfile(policy_path, backup_path)
    try:
        base = json.loads(policy_path.read_text(encoding="utf-8"))
        # Inject deny_hosts for default tenant http_get.simple
        base.setdefault("tenants", {}).setdefault("default", {}).setdefault("tools", {}).setdefault("http_get", {}).setdefault("names", {}).setdefault("simple", {}).setdefault("options", {})["deny_hosts"] = ["blocked.example"]
        policy_path.write_text(json.dumps(base), encoding="utf-8")
        tools_router._load_policies(force=True)

        url = "https://blocked.example/path"
        # no respx mock

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "tenant_id": "default",
                "tool_type": "http_get",
                "tool_name": "simple",
                "params": {"url": url},
            }
            r = await client.post("/api/v1/tools/invoke", json=payload)
            assert r.status_code == 403
            assert "deny_hosts" in r.text
    finally:
        shutil.copyfile(backup_path, policy_path)
        tools_router._load_policies(force=True)
        backup_path.unlink(missing_ok=True)
