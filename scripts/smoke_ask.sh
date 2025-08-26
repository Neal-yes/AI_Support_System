#!/usr/bin/env bash
set -euo pipefail

# 对统一问答接口 /api/v1/ask 进行冒烟验证
# 产物：artifacts/metrics/ask_plain.json, ask_rag.json

API_BASE=${API_BASE:-http://localhost:8000}
OUT_DIR=${OUT_DIR:-artifacts/metrics}
MODEL=${MODEL:-}
SMOKE_VERBOSE=${SMOKE_VERBOSE:-0}
SKIP_RAG=${SKIP_RAG:-0}
# Max seconds per curl call (overall). RAG may take longer; default 300.
SMOKE_MAX_TIME=${SMOKE_MAX_TIME:-300}

# curl options
CURL_OPTS=(--fail-with-body --connect-timeout 5 --max-time "$SMOKE_MAX_TIME")
if [ "$SMOKE_VERBOSE" = "1" ]; then
  set -x
  CURL_OPTS+=(-v)
fi

mkdir -p "$OUT_DIR"
# pre-create output files to ensure artifacts always contain something
: > "$OUT_DIR/ask_plain.json"
: > "$OUT_DIR/ask_rag.json"
: > "$OUT_DIR/ask_plain.status"
: > "$OUT_DIR/ask_rag.status"
echo "[SMOKE] API_BASE=$API_BASE MODEL=$MODEL OUT_DIR=$OUT_DIR SKIP_RAG=$SKIP_RAG" >&2

plain_body=$(jq -n \
  --arg model "$MODEL" \
  --arg q "你好，请用一句话自我介绍" \
  --argjson use_rag false \
  --argjson num_predict 48 \
  '
  ($model | length) as $ml |
  {
    query: $q,
    use_rag: $use_rag,
    options: { num_predict: $num_predict }
  } + ( if $ml > 0 then { model: $model } else {} end )
  ')

rag_body=$(jq -n \
  --arg model "$MODEL" \
  --arg q "如何查看 Prometheus 指标?" \
  --argjson use_rag true \
  --argjson top_k 5 \
  --argjson num_predict 48 \
  '
  ($model | length) as $ml |
  {
    query: $q,
    use_rag: $use_rag,
    top_k: $top_k,
    options: { num_predict: $num_predict }
  } + ( if $ml > 0 then { model: $model } else {} end )
  ')

call_once() {
  local body="$1" out="$2"
  curl -sS "${CURL_OPTS[@]}" -o "$out" -w "%{http_code}" -H 'Content-Type: application/json' -d "$body" "$API_BASE/api/v1/ask"
}

set +e
hc1=$(call_once "$plain_body" "$OUT_DIR/ask_plain.json"); rc1=$?
if [ $rc1 -ne 0 ] || [ "$hc1" != "200" ]; then
  echo "[SMOKE] plain attempt#1 failed: rc=$rc1 http=$hc1" >&2
  sed -n '1,160p' "$OUT_DIR/ask_plain.json" >&2 || true
  echo "[SMOKE] probing /metrics health before retry..." >&2
  curl -sS "${CURL_OPTS[@]}" -o "$OUT_DIR/metrics_plain_probe.txt" -w "HTTP %{http_code}\n" "$API_BASE/metrics" >&2 || true
  sleep 3
  hc1=$(call_once "$plain_body" "$OUT_DIR/ask_plain.json"); rc1=$?
  echo "[SMOKE] plain attempt#2 result: rc=$rc1 http=$hc1" >&2
  # if still failed and file empty, write an error stub for observability
  if [ $rc1 -ne 0 ] || [ "$hc1" != "200" ]; then
    if [ ! -s "$OUT_DIR/ask_plain.json" ]; then
      echo "{\"error\":\"plain ask failed\",\"rc\":$rc1,\"http\":\"$hc1\"}" > "$OUT_DIR/ask_plain.json" || true
    fi
  fi
fi
echo "rc=$rc1 http=$hc1" > "$OUT_DIR/ask_plain.status" || true

if [ "$SKIP_RAG" = "1" ]; then
  echo "[SMOKE] skipping RAG part as requested (SKIP_RAG=1)" >&2
  rc2=0; hc2=200
  echo "rc=$rc2 http=$hc2 skipped=1" > "$OUT_DIR/ask_rag.status" || true
  echo '{"skipped": true, "reason": "SKIP_RAG=1"}' > "$OUT_DIR/ask_rag.json" || true
else
  hc2=$(call_once "$rag_body" "$OUT_DIR/ask_rag.json"); rc2=$?
  if [ $rc2 -ne 0 ] || [ "$hc2" != "200" ]; then
    echo "[SMOKE] rag attempt#1 failed: rc=$rc2 http=$hc2" >&2
    sed -n '1,160p' "$OUT_DIR/ask_rag.json" >&2 || true
    echo "[SMOKE] probing /metrics health before retry..." >&2
    curl -sS "${CURL_OPTS[@]}" -o "$OUT_DIR/metrics_rag_probe.txt" -w "HTTP %{http_code}\n" "$API_BASE/metrics" >&2 || true
    sleep 3
    hc2=$(call_once "$rag_body" "$OUT_DIR/ask_rag.json"); rc2=$?
    echo "[SMOKE] rag attempt#2 result: rc=$rc2 http=$hc2" >&2
    # if still failed and file empty, write an error stub for observability
    if [ $rc2 -ne 0 ] || [ "$hc2" != "200" ]; then
      if [ ! -s "$OUT_DIR/ask_rag.json" ]; then
        echo "{\"error\":\"rag ask failed\",\"rc\":$rc2,\"http\":\"$hc2\"}" > "$OUT_DIR/ask_rag.json" || true
      fi
    fi
  fi
  echo "rc=$rc2 http=$hc2" > "$OUT_DIR/ask_rag.status" || true
fi
set -e

if [ $rc1 -ne 0 ] || [ "$hc1" != "200" ]; then
  echo "ask plain smoke failed: rc=$rc1 http=$hc1" >&2
  sed -n '1,200p' "$OUT_DIR/ask_plain.json" >&2 || true
  exit 1
fi
if [ "$SKIP_RAG" != "1" ] && { [ $rc2 -ne 0 ] || [ "$hc2" != "200" ]; }; then
  echo "ask rag smoke failed: rc=$rc2 http=$hc2" >&2
  sed -n '1,200p' "$OUT_DIR/ask_rag.json" >&2 || true
  exit 1
fi
echo "[SMOKE] both plain and rag succeeded: http1=$hc1 http2=$hc2" >&2

echo "[SMOKE] /api/v1/ask plain & rag OK"
