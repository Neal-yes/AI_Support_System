#!/usr/bin/env bash
set -euo pipefail

# 对统一问答接口 /api/v1/ask 进行冒烟验证
# 产物：artifacts/metrics/ask_plain.json, ask_rag.json

API_BASE=${API_BASE:-http://localhost:8000}
OUT_DIR=${OUT_DIR:-artifacts/metrics}
MODEL=${MODEL:-}
COLLECTION=${COLLECTION:-}
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
echo "[SMOKE] API_BASE=$API_BASE MODEL=$MODEL COLLECTION=${COLLECTION:-<unset>} OUT_DIR=$OUT_DIR SKIP_RAG=$SKIP_RAG" >&2

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
  --arg coll "$COLLECTION" \
  --argjson use_rag true \
  --argjson top_k 5 \
  --argjson num_predict 48 \
  '
  ($model | length) as $ml |
  ($coll | length) as $cl |
  {
    query: $q,
    use_rag: $use_rag,
    top_k: $top_k,
    options: { num_predict: $num_predict }
  }
  + ( if $ml > 0 then { model: $model } else {} end )
  + ( if $cl > 0 then { collection: $coll } else {} end )
  ')

call_once() {
  local body="$1" out="$2"
  curl -sS "${CURL_OPTS[@]}" -o "$out" -w "%{http_code}" -H 'Content-Type: application/json' -d "$body" "$API_BASE/api/v1/ask"
}

# Validate response JSON structure for observability (best-effort; requires jq)
validate_plain() {
  local file="$1"
  if ! command -v jq >/dev/null 2>&1; then return 0; fi
  # Must be valid JSON and meta.use_rag=false
  if ! jq -e . "$file" >/dev/null 2>&1; then
    echo "[SMOKE] plain: invalid JSON" >&2; return 1
  fi
  if ! jq -e '(.meta.use_rag == false) and ((.response | strings | length) >= 1)' "$file" >/dev/null 2>&1; then
    echo "[SMOKE] plain: meta.use_rag must be false and response non-empty" >&2; return 1
  fi
  return 0
}

validate_rag() {
  local file="$1"
  if ! command -v jq >/dev/null 2>&1; then return 0; fi
  if ! jq -e . "$file" >/dev/null 2>&1; then
    echo "[SMOKE] rag: invalid JSON" >&2; return 1
  fi
  # meta.use_rag must be true; sources must be a non-empty array
  # If COLLECTION (requested) is provided, response .meta.collection must match it
  if ! jq -e --arg coll "$COLLECTION" '
    (.meta.use_rag == true)
    and ((.sources | type=="array") and ((.sources | length) >= 1))
    and (((($coll | length) == 0)) or (.meta.collection == $coll))
  ' "$file" >/dev/null 2>&1; then
    echo "[SMOKE] rag: require meta.use_rag=true, sources non-empty, and when requested collection is set, meta.collection must match it" >&2; return 1
  fi
  return 0
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

# Prepare a brief markdown summary (write to temp first to avoid misleading success on later failures)
SUM_TMP="$OUT_DIR/smoke_summary.tmp.md"
SUM_FINAL="$OUT_DIR/smoke_summary.md"
{
  echo "## Smoke: /api/v1/ask"
  echo
  echo "- Plain: rc=$rc1 http=$hc1"
  if command -v jq >/dev/null 2>&1 && [ -s "$OUT_DIR/ask_plain.json" ]; then
    echo "  - response_len=$(jq -r '.response | strings | length // 0' "$OUT_DIR/ask_plain.json")"
    echo "  - use_rag=$(jq -r '.meta | if has("use_rag") then .use_rag else "null" end' "$OUT_DIR/ask_plain.json")"
  fi
  if [ "$SKIP_RAG" = "1" ]; then
    echo "- RAG: skipped"
  else
    echo "- RAG: rc=$rc2 http=$hc2"
    if command -v jq >/dev/null 2>&1 && [ -s "$OUT_DIR/ask_rag.json" ]; then
      # Precompute with safe fallbacks to avoid empty substitutions
      rag_sources_len=$(jq -r '.sources | if type=="array" then length else 0 end' "$OUT_DIR/ask_rag.json" 2>/dev/null || echo 0)
      rag_match=$(jq -r '.meta | if has("match") then .match else "null" end' "$OUT_DIR/ask_rag.json" 2>/dev/null || echo null)
      rag_resp_coll=$(jq -r '.meta.collection // "<none>"' "$OUT_DIR/ask_rag.json" 2>/dev/null || echo "<none>")
      echo "  - request_collection=${COLLECTION:-<default>} response_collection=${rag_resp_coll}"
      echo "  - sources_len=${rag_sources_len} match=${rag_match}"
    fi
  fi
} > "$SUM_TMP" || true

if [ $rc1 -ne 0 ] || [ "$hc1" != "200" ]; then
  echo "ask plain smoke failed: rc=$rc1 http=$hc1" >&2
  sed -n '1,200p' "$OUT_DIR/ask_plain.json" >&2 || true
  { echo "- result: FAIL (plain http rc=$rc1 http=$hc1)"; } >> "$SUM_TMP" || true
  mv -f "$SUM_TMP" "$SUM_FINAL" 2>/dev/null || true
  exit 1
fi
# Additional structure validation for plain
if ! validate_plain "$OUT_DIR/ask_plain.json"; then
  echo "ask plain validation failed" >&2
  sed -n '1,200p' "$OUT_DIR/ask_plain.json" >&2 || true
  { echo "- result: FAIL (plain validation)"; } >> "$SUM_TMP" || true
  mv -f "$SUM_TMP" "$SUM_FINAL" 2>/dev/null || true
  exit 1
fi
if [ "$SKIP_RAG" != "1" ] && { [ $rc2 -ne 0 ] || [ "$hc2" != "200" ]; }; then
  echo "ask rag smoke failed: rc=$rc2 http=$hc2" >&2
  sed -n '1,200p' "$OUT_DIR/ask_rag.json" >&2 || true
  { echo "- result: FAIL (rag http rc=$rc2 http=$hc2)"; } >> "$SUM_TMP" || true
  mv -f "$SUM_TMP" "$SUM_FINAL" 2>/dev/null || true
  exit 1
fi
# Additional structure validation for rag
if [ "$SKIP_RAG" != "1" ]; then
  if ! validate_rag "$OUT_DIR/ask_rag.json"; then
    echo "ask rag validation failed" >&2
    sed -n '1,200p' "$OUT_DIR/ask_rag.json" >&2 || true
    { echo "- result: FAIL (rag validation)"; } >> "$SUM_TMP" || true
    mv -f "$SUM_TMP" "$SUM_FINAL" 2>/dev/null || true
    exit 1
  fi
fi
echo "[SMOKE] both plain and rag succeeded: http1=$hc1 http2=$hc2" >&2

# 打印 RAG 请求与响应集合，便于 CI 日志快速确认
if [ "$SKIP_RAG" != "1" ] && command -v jq >/dev/null 2>&1; then
  resp_coll=$(jq -r '.meta.collection // "<none>"' "$OUT_DIR/ask_rag.json" 2>/dev/null || echo "<none>")
  echo "[SMOKE] RAG collection requested='${COLLECTION:-<default>}' response='${resp_coll}'" >&2
fi

{ echo "- result: PASS"; } >> "$SUM_TMP" || true
mv -f "$SUM_TMP" "$SUM_FINAL" 2>/dev/null || true

echo "[SMOKE] /api/v1/ask plain & rag OK"
