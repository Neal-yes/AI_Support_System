import os
import json
import pytest
import httpx

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
SKIP_E2E = os.getenv("SKIP_E2E", "0") == "1"


def _url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return BASE_URL.rstrip("/") + path


@pytest.mark.skipif(SKIP_E2E, reason="SKIP_E2E=1")
def test_healthz_ok():
    r = httpx.get(_url("/healthz"), timeout=5.0)
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["status"] in {"ok", "degraded"}


@pytest.mark.skipif(SKIP_E2E, reason="SKIP_E2E=1")
def test_preflight_200_and_ok_field():
    # Use minimal query; backend should soft-fail with ok=false on dependency errors instead of 500
    payload = {"query": "hello world"}
    r = httpx.post(_url("/api/v1/rag/preflight"), json=payload, timeout=10.0)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "ok" in data, f"missing 'ok' field in response: {json.dumps(data)}"
