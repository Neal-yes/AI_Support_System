#!/usr/bin/env bash
set -euo pipefail

# 备份 Qdrant 集合到 JSON（通过 scroll 导出 points）
# 产物：artifacts/metrics/qdrant_<collection>_dump.json
# 环境变量：
# - QDRANT_HTTP (默认 http://localhost:6333)
# - RAG_COLLECTION (默认读取后端 settings 默认集合，可为空时脚本尝试从 /embedding/upsert 响应推断，不可靠，建议显式传入)
# - SCROLL_LIMIT (每批次条数，默认 256)
# - CURL_CONNECT_TIMEOUT（秒，默认 2）
# - CURL_MAX_TIME（秒，默认 10）
# - MAX_BATCHES（最大批次数，默认 0 表示不限）

QDRANT_HTTP=${QDRANT_HTTP:-http://localhost:6333}
COLL=${RAG_COLLECTION:-}
SCROLL_LIMIT=${SCROLL_LIMIT:-256}
OUT_DIR=${OUT_DIR:-artifacts/metrics}
CURL_CONNECT_TIMEOUT=${CURL_CONNECT_TIMEOUT:-2}
CURL_MAX_TIME=${CURL_MAX_TIME:-10}
MAX_BATCHES=${MAX_BATCHES:-0}

if [ -z "${COLL}" ]; then
  # 使用后端默认集合名（和服务保持一致，默认 default_collection）
  COLL=${DEFAULT_COLLECTION:-default_collection}
fi

mkdir -p "$OUT_DIR"
OUT_FILE="${OUT_DIR}/qdrant_${COLL}_dump.json"

have_jq() { command -v jq >/dev/null 2>&1; }
if ! have_jq; then
  echo "jq 未安装，请先安装 jq" >&2
  exit 2
fi

# 逐批 scroll 导出
NEXT_PAGE="null"
> "$OUT_FILE"
echo '[' >> "$OUT_FILE"
FIRST=1

COUNT_TOTAL=0
BATCH=0
while :; do
  BODY=$(jq -n --argjson next "$NEXT_PAGE" --argjson lim "$SCROLL_LIMIT" '{limit: (if $lim==0 then 256 else $lim end), with_payload:true, with_vectors:false} + (if $next==null then {} else {offset: $next} end)')
  RESP=$(curl -sS --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" \
              -X POST -H 'Content-Type: application/json' -d "$BODY" \
              "$QDRANT_HTTP/collections/$COLL/points/scroll")
  # 基本校验
  if [ "$(echo "$RESP" | jq -r '.status')" != "ok" ]; then
    echo "导出失败：$RESP" >&2
    exit 1
  fi
  POINTS=$(echo "$RESP" | jq -c '.result.points')
  HAS_NEXT=$(echo "$RESP" | jq '.result.next_page_offset != null')
  NEXT_PAGE=$(echo "$RESP" | jq -c '.result.next_page_offset')

  COUNT=$(echo "$POINTS" | jq 'length')
  BATCH=$((BATCH+1))
  COUNT_TOTAL=$((COUNT_TOTAL+COUNT))
  echo "[BACKUP] batch=$BATCH items=$COUNT total=$COUNT_TOTAL next_page=$HAS_NEXT" >&2
  if [ "$COUNT" != "0" ]; then
    if [ $FIRST -eq 1 ]; then
      FIRST=0
    else
      echo ',' >> "$OUT_FILE"
    fi
    # 逐批写入数组元素（去掉外层 []）
    echo "$POINTS" | jq -c '.[]' | sed 's/^/ /' | paste -sd',' - >> "$OUT_FILE"
  fi

  # 达到最大批次则提前结束（用于避免长时间运行）
  if [ "$MAX_BATCHES" -gt 0 ] && [ "$BATCH" -ge "$MAX_BATCHES" ]; then
    echo "[BACKUP] 达到 MAX_BATCHES=$MAX_BATCHES，提前结束" >&2
    break
  fi

  if [ "$HAS_NEXT" != "true" ]; then
    break
  fi

done

echo ']' >> "$OUT_FILE"

echo "[BACKUP] Qdrant collection '$COLL' 导出完成：$OUT_FILE (batches=$BATCH total_items=$COUNT_TOTAL)"
