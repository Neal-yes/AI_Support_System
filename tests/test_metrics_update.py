import asyncio
import re

import pytest
import respx
from httpx import AsyncClient, ASGITransport, Response

from src.app.main import app


@pytest.mark.asyncio
@respx.mock
async def test_metrics_increment_after_invoke():
    # mock external http call
    url = "https://example.com/"
    respx.get(url).mock(return_value=Response(200, text="OK"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # snapshot metrics before
        m1 = await client.get("/metrics")
        before = m1.text

        payload = {
            "tenant_id": "t-metrics",
            "tool_type": "http_get",
            "tool_name": "simple",
            "params": {"url": url},
            "options": {"timeout_ms": 500}
        }
        r = await client.post("/api/v1/tools/invoke", json=payload)
        assert r.status_code == 200

        # metrics after
        m2 = await client.get("/metrics")
        after = m2.text

        # Assert requests_total increased for this label set (label order-insensitive)
        def find_count(s: str) -> int:
            # match lines like: tools_requests_total{...} 123
            for line in s.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # skip created lines
                if line.startswith("tools_requests_created"):
                    continue
                if not line.startswith("tools_requests_total"):
                    continue
                # extract labels and value
                try:
                    # find the first '{' after metric name
                    if "{" not in line or "}" not in line:
                        continue
                    labels_str, value_str = line.split("}", 1)
                    labels_str = labels_str.split("{", 1)[1]
                    labels = dict(re.findall(r"(\w+)=\"([^\"]*)\"", labels_str))
                    if labels.get("tool_type") == "http_get" and labels.get("tool_name") == "simple" and labels.get("tenant") == "t-metrics":
                        try:
                            return int(float(value_str.strip()))
                        except Exception:
                            return 0
                except Exception:
                    continue
            return 0

        c1 = find_count(before)
        c2 = find_count(after)
        assert c2 == c1 + 1
