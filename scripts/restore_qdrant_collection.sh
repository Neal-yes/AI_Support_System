#!/usr/bin/env bash
set -euo pipefail

# 从备份 JSON（scroll 导出的 points）恢复到 Qdrant 集合
# 方式：读取 payload.text 重建嵌入，通过 /embedding/upsert 写回（不依赖原向量）
# 注意：如需原向量级别恢复，请改为直接调用 Qdrant points upsert 接口并携带 vectors。
# 环境变量：
# - API_BASE (默认 http://localhost:8000)
# - RAG_COLLECTION 目标集合（默认 default_collection）
# - SRC_DUMP 备份文件路径（默认 artifacts/metrics/qdrant_<collection>_dump.json）
# - BATCH_SIZE (默认 64)

API_BASE=${API_BASE:-http://localhost:8000}
COLL=${RAG_COLLECTION:-default_collection}
BATCH_SIZE=${BATCH_SIZE:-64}
OUT_DIR=${OUT_DIR:-artifacts/metrics}
SRC_DUMP=${SRC_DUMP:-}
RAG_MODEL=${RAG_MODEL:-}

mkdir -p "$OUT_DIR"

have_jq() { command -v jq >/dev/null 2>&1; }
if ! have_jq; then
  echo "jq 未安装，请先安装 jq" >&2
  exit 2
fi

if [ -z "$SRC_DUMP" ]; then
  SRC_DUMP="${OUT_DIR}/qdrant_${COLL}_dump.json"
fi

if [ ! -f "$SRC_DUMP" ]; then
  echo "未找到备份文件: $SRC_DUMP" >&2
  exit 2
fi

COUNT=$(jq 'length' "$SRC_DUMP")
if [ "$COUNT" = "0" ]; then
  echo "备份为空：$SRC_DUMP" >&2
  exit 0
fi

echo "[RESTORE] 从 $SRC_DUMP 恢复 $COUNT 条到集合 $COLL（batch=$BATCH_SIZE）"

OFFSET=0
TOTAL=0

while [ $OFFSET -lt $COUNT ]; do
  SIZE=$(( COUNT - OFFSET ))
  if [ $SIZE -gt $BATCH_SIZE ]; then SIZE=$BATCH_SIZE; fi
  SLICE=$(jq ".[$OFFSET:($OFFSET+$SIZE)]" "$SRC_DUMP")
  TEXTS=$(echo "$SLICE" | jq -c '[ .[].payload.text | select(type=="string") ]')
  PAYLOADS=$(echo "$SLICE" | jq -c '[ .[].payload ]')

  # 跳过空批
  if [ "$(echo "$TEXTS" | jq 'length')" = "0" ]; then
    OFFSET=$(( OFFSET + SIZE ))
    continue
  }

  BODY=$(jq -n \
    --argjson texts "$TEXTS" \
    --argjson payloads "$PAYLOADS" \
    --arg coll "$COLL" \
    --arg model "${RAG_MODEL}" '
      {texts:$texts, payloads:$payloads, collection:$coll}
      + (if $model == "" then {} else {model:$model} end)
    ')

  set +e
  HC=$(curl -sS -o /tmp/restore_upsert.json -w "%{http_code}" -H 'Content-Type: application/json' -d "$BODY" "$API_BASE/embedding/upsert")
  RC=$?
  set -e
  if [ $RC -ne 0 ] || [ "$HC" != "200" ]; then
    echo "[RESTORE] upsert 失败: rc=$RC http=$HC offset=$OFFSET size=$SIZE" >&2
    sed -n '1,120p' /tmp/restore_upsert.json >&2 || true
    exit 1
  fi
  CNT=$(jq -r '.count // 0' /tmp/restore_upsert.json)
  TOTAL=$(( TOTAL + CNT ))
  echo "[RESTORE] 本批 $CNT 条，累计 $TOTAL"

  OFFSET=$(( OFFSET + SIZE ))

done

echo "[RESTORE] 完成，共恢复 $TOTAL 条到 $COLL"
