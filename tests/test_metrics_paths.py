import re
import uuid

import pytest
import respx
from httpx import AsyncClient, ASGITransport, Response

from src.app.main import app


def _find_metric_value(text: str, metric_name: str, match_labels: dict) -> int:
    # Robust parsing: ignore comments/created lines, accept any label order, parse float->int
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not line.startswith(metric_name):
            continue
        if '{' not in line or '}' not in line:
            continue
        labels_part, value_part = line.split('}', 1)
        labels_str = labels_part.split('{', 1)[1]
        labels = dict(re.findall(r"(\w+)=\"([^\"]*)\"", labels_str))
        ok = all(labels.get(k) == v for k, v in match_labels.items())
        if ok:
            try:
                return int(float(value_part.strip()))
            except Exception:
                return 0
    return 0


@pytest.mark.asyncio
@respx.mock
async def test_error_exec_failure_metric():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # snapshot before
        before = (await client.get("/metrics")).text

        # trigger execution failure with simulate_fail
        url = "https://example.com/"
        respx.get(url).mock(return_value=Response(200, text="OK"))
        payload = {
            "tenant_id": f"t-{uuid.uuid4()}",
            "tool_type": "http_get",
            "tool_name": "simple",
            "params": {"url": url},
            "options": {"timeout_ms": 500, "retry_max": 0, "simulate_fail": True},
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 502

        after = (await client.get("/metrics")).text
        labels = {"tool_type": "http_get", "tool_name": "simple", "tenant": payload["tenant_id"], "reason": "exec_failure"}
        c1 = _find_metric_value(before, "tools_errors_total", labels)
        c2 = _find_metric_value(after, "tools_errors_total", labels)
        assert c2 == c1 + 1


@pytest.mark.asyncio
@respx.mock
async def test_rate_limited_metric():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/metrics")).text
        url = "https://example.org/"
        respx.get(url).mock(return_value=Response(200, text="OK"))
        tenant = f"t-{uuid.uuid4()}"
        payload = {
            "tenant_id": tenant,
            "tool_type": "http_get",
            "tool_name": "rl_demo",
            "params": {"url": url},
            "options": {"timeout_ms": 500, "rate_limit_per_sec": 1},
        }
        # Rapidly send several requests to avoid crossing second boundary flakiness
        statuses = []
        for _ in range(5):
            resp = await client.post("/api/v1/tools/invoke", json=payload)
            statuses.append(resp.status_code)
        # At least one rate-limited response is expected when limit=1
        assert any(s == 429 for s in statuses)
        after = (await client.get("/metrics")).text
        labels = {"tool_type": "http_get", "tool_name": "rl_demo", "tenant": tenant}
        c1 = _find_metric_value(before, "tools_rate_limited_total", labels)
        c2 = _find_metric_value(after, "tools_rate_limited_total", labels)
        assert c2 >= c1 + 1


@pytest.mark.asyncio
@respx.mock
async def test_circuit_open_metric():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/metrics")).text
        url = "https://example.net/"
        respx.get(url).mock(return_value=Response(200, text="OK"))
        tenant = f"t-{uuid.uuid4()}"
        base_payload = {
            "tenant_id": tenant,
            "tool_type": "http_get",
            "tool_name": "cb_demo",
            "params": {"url": url},
            "options": {"timeout_ms": 500, "circuit_threshold": 1, "circuit_cooldown_ms": 30000},
        }
        # First call fails and trips breaker
        p1 = {**base_payload, "options": {**base_payload["options"], "retry_max": 0, "simulate_fail": True}}
        r1 = await client.post("/api/v1/tools/invoke", json=p1)
        assert r1.status_code == 502
        # Second call should be blocked by circuit
        r2 = await client.post("/api/v1/tools/invoke", json=base_payload)
        assert r2.status_code == 503

        after = (await client.get("/metrics")).text
        labels = {"tool_type": "http_get", "tool_name": "cb_demo", "tenant": tenant}
        c1 = _find_metric_value(before, "tools_circuit_open_total", labels)
        c2 = _find_metric_value(after, "tools_circuit_open_total", labels)
        assert c2 == c1 + 1


@pytest.mark.asyncio
@respx.mock
async def test_cache_hit_metric():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/metrics")).text
        url = "https://example.info/"
        respx.get(url).mock(return_value=Response(200, text="OK"))
        tenant = f"t-{uuid.uuid4()}"
        payload = {
            "tenant_id": tenant,
            "tool_type": "http_get",
            "tool_name": "cache_demo",
            "params": {"url": url},
            "options": {"timeout_ms": 500, "cache_ttl_ms": 60000},
        }
        r1 = await client.post("/api/v1/tools/invoke", json=payload)
        assert r1.status_code == 200
        r2 = await client.post("/api/v1/tools/invoke", json=payload)
        assert r2.status_code == 200
        after = (await client.get("/metrics")).text
        labels = {"tool_type": "http_get", "tool_name": "cache_demo", "tenant": tenant}
        c1 = _find_metric_value(before, "tools_cache_hit_total", labels)
        c2 = _find_metric_value(after, "tools_cache_hit_total", labels)
        assert c2 == c1 + 1


@pytest.mark.asyncio
@respx.mock
async def test_retries_metric():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        before = (await client.get("/metrics")).text
        tenant = f"t-{uuid.uuid4()}"
        payload = {
            "tenant_id": tenant,
            "tool_type": "http_get",
            "tool_name": "retry_demo",
            "params": {"url": "https://any.example/"},
            "options": {"timeout_ms": 100, "retry_max": 1, "retry_backoff_ms": 10, "simulate_fail": True},
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 502
        after = (await client.get("/metrics")).text
        labels = {"tool_type": "http_get", "tool_name": "retry_demo", "tenant": tenant}
        c1 = _find_metric_value(before, "tools_retries_total", labels)
        c2 = _find_metric_value(after, "tools_retries_total", labels)
        assert c2 == c1 + 1
