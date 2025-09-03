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
async def test_tools_policy_hot_reload_effects_immediately():
    policy_path = Path("configs/tools_policies.json")
    assert policy_path.exists(), "tools_policies.json must exist for this test"

    # Backup original
    backup_path = policy_path.with_suffix(".json.bak")
    shutil.copyfile(policy_path, backup_path)

    try:
        # Write a modified policy: set resp_max_chars to 1234 for default tenant http_get.simple
        new_policy = {
            "default": {"options": {"timeout_ms": 3000, "resp_max_chars": 2048}},
            "tenants": {
                "default": {
                    "options": {},
                    "tools": {
                        "http_get": {
                            "options": {"timeout_ms": 3000},
                            "names": {"simple": {"options": {"resp_max_chars": 1234}}}
                        }
                    }
                }
            }
        }
        policy_path.write_text(json.dumps(new_policy), encoding="utf-8")

        # Force refresh the in-memory cache
        tools_router._load_policies(force=True)

        # Mock external HTTP
        url = "https://example.com/very-large"
        respx.get(url).mock(return_value=Response(200, text="X" * 10000))

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
            assert len(data["result"]["body"]) == 1234
    finally:
        # Restore file and refresh cache
        shutil.copyfile(backup_path, policy_path)
        tools_router._load_policies(force=True)
        backup_path.unlink(missing_ok=True)
