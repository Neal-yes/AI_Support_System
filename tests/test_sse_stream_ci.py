import os
import time
import pytest
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

skip_e2e = os.getenv("SKIP_E2E") == "1"

pytestmark = pytest.mark.skipif(skip_e2e, reason="SKIP_E2E=1")


def _iter_sse_lines(resp):
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        yield line


def test_ask_stream_minimal_plain_ok():
    url = f"{API_BASE_URL}/api/v1/ask/stream"
    payload = {
        "query": "用一句话回答：SSE 测试。",
        "use_rag": False,
        "options": {
            "num_predict": 8,
            "heartbeat_ms": 500,
            "time_limit_ms": 4000,
            "max_tokens_streamed": 4,
        },
    }
    with requests.post(url, json=payload, stream=True, timeout=15) as r:
        assert r.status_code == 200
        # Basic SSE headers are not strictly required, but often present
        ctype = r.headers.get("content-type", "")
        assert "text/event-stream" in ctype

        started = False
        got_data = False
        t0 = time.time()
        for line in _iter_sse_lines(r):
            # defensive time cap to avoid hang
            if time.time() - t0 > 8:
                break
            if line.startswith("data: "):
                payload = line[len("data: "):]
                if payload == "[started]":
                    started = True
                elif payload and not payload.startswith("[heartbeat]"):
                    got_data = True
                    break
        assert started, "SSE did not start"
        assert got_data, "No non-heartbeat data received from ask/stream"
