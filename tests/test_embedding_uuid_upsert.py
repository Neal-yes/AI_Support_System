import os
import uuid
import json
import pytest
import httpx

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
SKIP_E2E = os.getenv("SKIP_E2E", "0") == "1"
COLLECTION = os.getenv("TEST_COLLECTION", "demo_768")


def _url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return BASE_URL.rstrip("/") + path


@pytest.mark.skipif(SKIP_E2E, reason="SKIP_E2E=1")
def test_uuid_upsert_search_preflight_end_to_end():
    # 1) 生成唯一 UUID 与文本
    uid = str(uuid.uuid4())
    text = f"uuid-upsert-test {uid}"

    # 2) 覆盖 upsert（允许字符串 UUID）
    upsert_payload = {
        "collection": COLLECTION,
        "ids": [uid],
        "texts": [text],
        "payloads": [{"text": text}],
    }
    r = httpx.post(_url("/embedding/upsert"), json=upsert_payload, timeout=30.0)
    assert r.status_code == 200, f"upsert failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("count") == 1, f"unexpected upsert count: {json.dumps(data)}"

    # 3) Search 使用 UUID 作为查询，确保命中并带有 payload.text
    search_payload = {
        "query": uid,
        "top_k": 3,
        "collection": COLLECTION,
    }
    r = httpx.post(_url("/embedding/search"), json=search_payload, timeout=30.0)
    assert r.status_code == 200, f"search failed: {r.status_code} {r.text}"
    s = r.json()
    assert isinstance(s, dict) and "matches" in s, f"unexpected search response: {json.dumps(s)}"
    matches = s.get("matches", [])
    assert len(matches) > 0, "no search matches returned"
    # 找到目标 UUID 的命中
    target = next((m for m in matches if str(m.get("id")) == uid), None)
    assert target is not None, f"uuid {uid} not found in matches: {json.dumps(matches)}"
    assert isinstance(target.get("payload"), dict), f"payload missing for {uid}: {json.dumps(target)}"
    assert target["payload"].get("text") == text, f"payload.text mismatch: {json.dumps(target)}"

    # 4) RAG 预检，使用同一查询应能召回该来源
    preflight_payload = {
        "query": uid,
        "top_k": 3,
        "collection": COLLECTION,
    }
    r = httpx.post(_url("/api/v1/rag/preflight"), json=preflight_payload, timeout=30.0)
    assert r.status_code == 200, f"preflight failed: {r.status_code} {r.text}"
    p = r.json()
    assert p.get("ok") is True, f"preflight ok!=true: {json.dumps(p)}"
    assert p.get("contexts_count", 0) >= 1, f"contexts_count<1: {json.dumps(p)}"
    assert isinstance(p.get("sources"), list) and len(p["sources"]) >= 1, f"no sources: {json.dumps(p)}"
    src = next((x for x in p["sources"] if str(x.get("id")) == uid), None)
    assert src is not None, f"uuid {uid} not in preflight sources: {json.dumps(p)}"
    assert isinstance(src.get("payload"), dict) and src["payload"].get("text") == text, \
        f"preflight payload.text mismatch: {json.dumps(src)}"
