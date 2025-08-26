#!/usr/bin/env bash
set -euo pipefail

# 将 demo_faq.jsonl 的 question（兼容 query/prompt）批量嵌入并 upsert 到 Qdrant
# 依赖 API 路由：POST /embedding/upsert
# 产物：artifacts/metrics/embedding_upsert.json（汇总）

API_BASE=${API_BASE:-http://localhost:8000}
RAG_COLLECTION=${RAG_COLLECTION:-}
RAG_MODEL=${RAG_MODEL:-}
SRC_JSONL=${SRC_JSONL:-demo_faq.jsonl}
BATCH_SIZE=${BATCH_SIZE:-64}
MAX_DOCS=${MAX_DOCS:-500}
OUT_DIR=${OUT_DIR:-artifacts/metrics}

mkdir -p "$OUT_DIR"

have_jq() { command -v jq >/dev/null 2>&1; }
if ! have_jq; then
  echo "jq 未安装，请先安装 jq" >&2
  exit 2
fi

# Ensure SRC_JSONL exists with fallbacks
if [ ! -f "$SRC_JSONL" ]; then
  echo "找不到评测源文件: $SRC_JSONL，尝试回退..." >&2
  # Try gz counterpart
  if [ -f "${SRC_JSONL}.gz" ]; then
    echo "发现压缩文件 ${SRC_JSONL}.gz，解压生成 ${SRC_JSONL}"
    gunzip -c "${SRC_JSONL}.gz" > "$SRC_JSONL"
  # Try demo.jsonl family in repo root
  elif [ -f "demo_faq.jsonl" ]; then
    SRC_JSONL="demo_faq.jsonl"
    echo "使用回退源: $SRC_JSONL"
  elif [ -f "demo_faq.jsonl.gz" ]; then
    echo "发现 demo_faq.jsonl.gz，解压生成 demo_faq.jsonl"
    gunzip -c "demo_faq.jsonl.gz" > "demo_faq.jsonl"
    SRC_JSONL="demo_faq.jsonl"
  elif [ -f "demo.jsonl" ]; then
    SRC_JSONL="demo.jsonl"
    echo "使用回退源: $SRC_JSONL"
  elif [ -f "demo.jsonl.gz" ]; then
    echo "发现 demo.jsonl.gz，解压生成 demo.jsonl"
    gunzip -c "demo.jsonl.gz" > "demo.jsonl"
    SRC_JSONL="demo.jsonl"
  else
    echo "仍未找到可用评测源文件" >&2
    exit 2
  fi
fi

# 预处理：提取文本与简要 payload（如 tag/question/answer）
TMP_JSON=$(mktemp)
awk 'NR<='"${MAX_DOCS}"' {print}' "$SRC_JSONL" \
  | jq -s '[ .[] | { text: (.question // .query // .prompt // .text // ""), payload: { tag: (.tag // null), question: (.question // .query // .prompt // null), answer: (.answer // null) } } | select(.text != "") ]' > "$TMP_JSON"

COUNT=$(jq 'length' "$TMP_JSON")
if [ "$COUNT" = "0" ]; then
  echo "未从 $SRC_JSONL 提取到有效文本" >&2
  exit 2
fi

echo "[EMBED PREP] 将写入 ${COUNT} 条到 Qdrant（batch=${BATCH_SIZE} collection=${RAG_COLLECTION:-<default>} model=${RAG_MODEL:-<default>}）"

OFFSET=0
TOTAL_UPSERT=0
SUMMARY_JSON="${OUT_DIR}/embedding_upsert.json"
echo '{}' > "$SUMMARY_JSON"

while [ $OFFSET -lt $COUNT ]; do
  SIZE=$(( COUNT - OFFSET ))
  if [ $SIZE -gt $BATCH_SIZE ]; then SIZE=$BATCH_SIZE; fi
  BSLICE=$(jq ".[$OFFSET:($OFFSET+$SIZE)]" "$TMP_JSON")
  TEXTS=$(echo "$BSLICE" | jq '[ .[].text ]')
  PAYLOADS=$(echo "$BSLICE" | jq '[ .[].payload ]')

  BODY=$(jq -n \
    --argjson texts "$TEXTS" \
    --argjson payloads "$PAYLOADS" \
    --arg coll "${RAG_COLLECTION}" \
    --arg model "${RAG_MODEL}" '
      {
        texts: $texts,
        payloads: $payloads
      }
      + (if $coll == "" then {} else {collection: $coll} end)
      + (if $model == "" then {} else {model: $model} end)
    ')

  set +e
  HTTP_CODE=$(curl -sS -o /tmp/upsert_resp.json -w "%{http_code}" \
    -H 'Content-Type: application/json' \
    -d "$BODY" \
    "${API_BASE}/embedding/upsert")
  RC=$?
  set -e
  if [ $RC -ne 0 ] || [ "$HTTP_CODE" != "200" ]; then
    echo "[EMBED PREP] upsert 失败: rc=$RC http=$HTTP_CODE offset=$OFFSET size=$SIZE" >&2
    sed -n '1,120p' /tmp/upsert_resp.json >&2 || true
    # persist response for diagnostics
    cp -f /tmp/upsert_resp.json "$OUT_DIR/upsert_resp.json" 2>/dev/null || true
    exit 1
  fi

  CNT=$(jq -r '.count // 0' /tmp/upsert_resp.json)
  TOTAL_UPSERT=$(( TOTAL_UPSERT + CNT ))
  echo "[EMBED PREP] upsert 成功，本批 $CNT 条，累计 $TOTAL_UPSERT"

  OFFSET=$(( OFFSET + SIZE ))
done

jq -n --arg total "$TOTAL_UPSERT" --arg src "$SRC_JSONL" --arg coll "${RAG_COLLECTION}" '{total: ($total|tonumber), src: $src, collection: $coll}' > "$SUMMARY_JSON"

echo "[EMBED PREP] 完成，总 upsert 条数: $TOTAL_UPSERT，详情见 $SUMMARY_JSON"
