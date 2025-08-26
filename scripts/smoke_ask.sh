#!/usr/bin/env bash
set -euo pipefail

# 对统一问答接口 /api/v1/ask 进行冒烟验证
# 产物：artifacts/metrics/ask_plain.json, ask_rag.json

API_BASE=${API_BASE:-http://localhost:8000}
OUT_DIR=${OUT_DIR:-artifacts/metrics}
MODEL=${MODEL:-}

mkdir -p "$OUT_DIR"

plain_body=$(jq -n --arg model "$MODEL" '{query:"你好，请用一句话自我介绍", use_rag:false} + ( $model=="" ? {} : {model:$model} )')
rag_body=$(jq -n --arg model "$MODEL" '{query:"如何查看 Prometheus 指标?", use_rag:true, top_k:5} + ( $model=="" ? {} : {model:$model} )')

call_once() {
  local body="$1" out="$2"
  curl -sS -o "$out" -w "%{http_code}" -H 'Content-Type: application/json' -d "$body" "$API_BASE/api/v1/ask"
}

set +e
hc1=$(call_once "$plain_body" "$OUT_DIR/ask_plain.json"); rc1=$?
if [ $rc1 -ne 0 ] || [ "$hc1" != "200" ]; then
  echo "[SMOKE] plain attempt#1 failed: rc=$rc1 http=$hc1" >&2
  sed -n '1,160p' "$OUT_DIR/ask_plain.json" >&2 || true
  sleep 3
  hc1=$(call_once "$plain_body" "$OUT_DIR/ask_plain.json"); rc1=$?
  echo "[SMOKE] plain attempt#2 result: rc=$rc1 http=$hc1" >&2
fi

hc2=$(call_once "$rag_body" "$OUT_DIR/ask_rag.json"); rc2=$?
if [ $rc2 -ne 0 ] || [ "$hc2" != "200" ]; then
  echo "[SMOKE] rag attempt#1 failed: rc=$rc2 http=$hc2" >&2
  sed -n '1,160p' "$OUT_DIR/ask_rag.json" >&2 || true
  sleep 3
  hc2=$(call_once "$rag_body" "$OUT_DIR/ask_rag.json"); rc2=$?
  echo "[SMOKE] rag attempt#2 result: rc=$rc2 http=$hc2" >&2
fi
set -e

if [ $rc1 -ne 0 ] || [ "$hc1" != "200" ]; then
  echo "ask plain smoke failed: rc=$rc1 http=$hc1" >&2
  sed -n '1,200p' "$OUT_DIR/ask_plain.json" >&2 || true
  exit 1
fi
if [ $rc2 -ne 0 ] || [ "$hc2" != "200" ]; then
  echo "ask rag smoke failed: rc=$rc2 http=$hc2" >&2
  sed -n '1,200p' "$OUT_DIR/ask_rag.json" >&2 || true
  exit 1
fi

echo "[SMOKE] /api/v1/ask plain & rag OK"
