#!/usr/bin/env python3
"""
Validate backup-restore artifacts.
- embedding_upsert.json: expect fields total=5, src=demo.jsonl, collection=default_collection (defaults can be overridden)
- qdrant_<collection>_dump.json: expect a list with expected length (defaults to 5)

Usage:
  python scripts/validate_backup_artifacts.py \
    --emb artifacts/metrics/embedding_upsert.json \
    --dump artifacts/metrics/qdrant_default_collection_dump.json \
    --expect-total 5 \
    --expect-src demo.jsonl \
    --expect-collection default_collection

Exits non-zero on validation failure. Prints a short report and, when $GITHUB_STEP_SUMMARY is set,
appends a markdown block.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--emb", required=True)
    p.add_argument("--dump", required=True)
    p.add_argument("--expect-total", type=int, default=5)
    p.add_argument("--expect-src", default="demo.jsonl")
    p.add_argument("--expect-collection", default="default_collection")
    p.add_argument("--sample-count", type=int, default=3, help="Number of sample points to print on failure")
    args = p.parse_args()

    emb_path = Path(args.emb)
    dump_path = Path(args.dump)

    ok = True
    lines = []

    # Check embedding_upsert.json
    try:
        e = load_json(emb_path)
        total = e.get("total")
        src = e.get("src")
        coll = e.get("collection")
        lines.append(f"embedding_upsert.json: total={total} src={src} collection={coll}")
        if total != args.expect_total:
            ok = False
            lines.append(f"ASSERT FAIL: total == {args.expect_total}")
        if src != args.expect_src:
            ok = False
            lines.append(f"ASSERT FAIL: src == {args.expect_src}")
        if coll != args.expect_collection:
            ok = False
            lines.append(f"ASSERT FAIL: collection == {args.expect_collection}")
    except Exception as ex:
        ok = False
        lines.append(f"ERROR reading {emb_path}: {ex}")

    # Check qdrant dump
    try:
        d = load_json(dump_path)
        if isinstance(d, dict):
            points = d.get("points", [])
        elif isinstance(d, list):
            points = d
        else:
            points = []
        plen = len(points)
        lines.append(f"qdrant_dump: type={type(points).__name__} len={plen}")
        # If we know expected total, also assert
        if args.expect_total is not None and plen != args.expect_total:
            ok = False
            lines.append(f"ASSERT FAIL: points length == {args.expect_total}")
        # sample keys
        if plen:
            sample = points[0]
            if isinstance(sample, dict):
                sample_keys = list(sample.keys())
                lines.append(f"qdrant_dump sample keys: {sample_keys}")
    except Exception as ex:
        ok = False
        lines.append(f"ERROR reading {dump_path}: {ex}")

    # On failure, include first N sample points for quick diagnosis (id + selected payload fields)
    if not ok:
        try:
            samples = []
            for item in points[: max(0, args.sample_count)]:
                if isinstance(item, dict):
                    pid = item.get("id")
                    payload = item.get("payload", {}) or {}
                    preview = {k: payload.get(k) for k in ("tag", "text", "question", "answer") if k in payload}
                    samples.append({"id": pid, "payload": preview})
                else:
                    samples.append(str(item)[:200])
            if samples:
                lines.append("samples:")
                for i, s in enumerate(samples, 1):
                    lines.append(f"  - [{i}] {s}")
        except Exception as ex:
            lines.append(f"ERROR generating samples preview: {ex}")

    # Print report
    report = "\n".join(lines)
    print(report)

    # Append to GITHUB_STEP_SUMMARY if available
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n\n### Artifact Validation\n\n")
            f.write("```text\n")
            f.write(report)
            f.write("\n```\n")

    if not ok:
        print("Validation failed", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
