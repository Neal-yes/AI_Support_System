#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量 re-upsert 脚本（支持 UUID），用于安全补齐历史缺失的 payload.text。

用法示例：

python scripts/batch_reupsert.py \
  --input demo.jsonl \
  --collection demo_768 \
  --base-url http://127.0.0.1:8000 \
  --batch-size 64

输入文件（JSONL，一行一个 JSON 对象）：
- 最小字段：{"text":"可通过脚本导入 demo 数据，也可从 jsonl 导入 FAQ"}
- 可选字段：{"id":"uuid-or-int","text":"...","payload":{"text":"...","tag":"faq"}}
  - 若未提供 payload，将自动补 `{ "text": 原文 }`
  - 若未提供 id，则由后端/Qdrant 自动生成。

脚本行为：
- 将带 id 与不带 id 的记录分开分批 upsert（避免传入 ids 列表与 texts/payloads 长度不一致或混合 None）。
- 失败会打印响应体与状态码；成功会打印累计计数。
"""

import argparse
import json
from typing import Any, Dict, List, Optional, Union
import httpx
import sys


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError("entry is not a JSON object")
            except Exception as e:
                raise RuntimeError(f"invalid JSONL at line {ln}: {e}")
            if "text" not in obj or not isinstance(obj["text"], str) or not obj["text"].strip():
                raise RuntimeError(f"line {ln} missing non-empty 'text'")
            items.append(obj)
    return items


def chunk(lst: List[Any], size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def do_upsert(client: httpx.Client, base_url: str, collection: str, batch: List[Dict[str, Any]]) -> None:
    texts: List[str] = []
    payloads: List[Dict[str, Any]] = []
    ids: List[Union[int, str]] = []
    all_have_id = True

    for obj in batch:
        txt = str(obj.get("text", ""))
        texts.append(txt)
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            payload = {"text": txt}
        payloads.append(payload)
        if "id" in obj and obj["id"] is not None:
            ids.append(obj["id"])  # may be int or str
        else:
            all_have_id = False

    body: Dict[str, Any] = {
        "collection": collection,
        "texts": texts,
        "payloads": payloads,
    }
    if all_have_id:
        body["ids"] = ids

    r = client.post(f"{base_url.rstrip('/')}/embedding/upsert", json=body, timeout=60.0)
    if r.status_code != 200:
        raise RuntimeError(f"upsert failed: {r.status_code} {r.text}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch re-upsert texts (UUID supported)")
    ap.add_argument("--input", required=True, help="Path to JSONL file")
    ap.add_argument("--collection", required=True, help="Target Qdrant collection")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    ap.add_argument("--batch-size", type=int, default=64, help="Batch size for each upsert")
    args = ap.parse_args()

    items = load_jsonl(args.input)
    if not items:
        print("no items to upsert", file=sys.stderr)
        return 1

    ok = 0
    with httpx.Client() as client:
        for part in chunk(items, args.batch_size):
            do_upsert(client, args.base_url, args.collection, part)
            ok += len(part)
            print(f"upserted {ok}/{len(items)}", flush=True)

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
