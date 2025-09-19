#!/usr/bin/env bash
set -euo pipefail

# 从备份 JSON（scroll 导出的 points）恢复到 Qdrant 集合
# 方式：读取 payload.text，通过 /embedding/embed 生成向量，并使用 Qdrant points/overwrite 直接写入目标集合
# 优点：不依赖后端 /embedding/upsert 的集合选择逻辑，确保写入到指定集合
# 环境变量：
# - API_BASE (默认 http://localhost:8000)
# - RAG_COLLECTION 目标集合（默认 default_collection）
# - SRC_DUMP 备份文件路径（默认 artifacts/metrics/qdrant_<collection>_dump.json）
# - BATCH_SIZE (默认 64)

API_BASE=${API_BASE:-http://localhost:8000}
QDRANT_HTTP=${QDRANT_HTTP:-http://localhost:6333}
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

set +u
echo "[RESTORE] API_BASE=${API_BASE} COLL=${COLL} SRC_DUMP=${SRC_DUMP} BATCH_SIZE=${BATCH_SIZE}" >&2
echo "[RESTORE] count=${COUNT} target=${COLL} batch=${BATCH_SIZE} src=${SRC_DUMP}" >&2
set -u

OFFSET=0
TOTAL=0

while [ $OFFSET -lt $COUNT ]; do
  SIZE=$(( COUNT - OFFSET ))
  if [ $SIZE -gt $BATCH_SIZE ]; then SIZE=$BATCH_SIZE; fi
  SLICE=$(jq ".[$OFFSET:($OFFSET+$SIZE)]" "$SRC_DUMP")
  # 仅保留 payload.text 为字符串的条目，确保与 embeddings 对齐
  FS=$(echo "$SLICE" | jq '[ .[] | select(.payload.text | type=="string") ]')
  TEXTS=$(echo "$FS" | jq -c '[ .[].payload.text ]')
  PAYLOADS=$(echo "$FS" | jq -c '[ .[].payload ]')

  # 跳过空批
  if [ "$(echo "$TEXTS" | jq -r 'length')" = "0" ]; then
    OFFSET=$(( OFFSET + SIZE ))
    continue
  fi

  # 1) 先生成向量
  if [ -n "${RAG_MODEL}" ]; then
    EMB_BODY=$(jq -n --argjson texts "$TEXTS" --arg model "${RAG_MODEL}" '{texts:$texts, model:$model}')
  else
    EMB_BODY=$(jq -n --argjson texts "$TEXTS" '{texts:$texts}')
  fi
  ATT=1
  while :; do
    set +e
    EMB_HTTP=$(curl -sS --connect-timeout 2 --max-time 20 -o /tmp/restore_embed.json -w "%{http_code}" -H 'Content-Type: application/json' -d "$EMB_BODY" "$API_BASE/embedding/embed")
    RC=$?
    set -e
    if [ $RC -eq 0 ] && [ "$EMB_HTTP" = "200" ]; then
      break
    fi
    echo "[RESTORE] embed 失败: rc=$RC http=$EMB_HTTP offset=$OFFSET size=$SIZE attempt=$ATT" >&2
    sed -n '1,120p' /tmp/restore_embed.json >&2 || true
    if [ $ATT -ge 3 ]; then
      echo "[RESTORE] embed 多次重试仍失败，终止" >&2
      exit 1
    fi
    sleep $(( ATT * 2 ))
    ATT=$(( ATT + 1 ))
  done
  VECTORS=$(jq -c '.embeddings // []' /tmp/restore_embed.json)
  FS_LEN=$(echo "$FS" | jq 'length')
  VEC_LEN=$(echo "$VECTORS" | jq 'length')
  echo "[RESTORE] batch lens: fs=${FS_LEN} vec=${VEC_LEN}"
  
  # 2) 组装 Qdrant points（仅对齐过滤后的切片，与 embeddings 一一对应），统一使用命名向量字段 text
  POINTS=$(jq -n --argjson slice "$FS" --argjson vecs "$VECTORS" --argjson off $OFFSET '
    [ range(0; ($vecs|length)) as $i | {
        id: (if ($slice[$i].id != null) then $slice[$i].id else ($i + $off) end),
        vectors: { text: ($vecs[$i] // []) },
        payload: ($slice[$i].payload // {})
      } ]')
  UPSERT_BODY=$(jq -n --argjson points "$POINTS" '{points:$points}')
  # 打印首个点的 id 作为样例
  SAMPLE_ID=$(echo "$POINTS" | jq -r '.[0].id // "<none>"')
  echo "[RESTORE] sample point id: ${SAMPLE_ID}"

  # 3) 写入 Qdrant（标准 upsert）
  ATT=1
  while :; do
    set +e
    Q_HTTP=$(curl -sS --connect-timeout 2 --max-time 20 -o /tmp/qdr_upsert.json -w "%{http_code}" \
      -X PUT -H 'Content-Type: application/json' -d "$UPSERT_BODY" \
      "$QDRANT_HTTP/collections/$COLL/points?wait=true")
    RC=$?
    set -e
    if [ $RC -eq 0 ] && [ "$Q_HTTP" = "200" ]; then
      break
    fi
    echo "[RESTORE] qdrant upsert 失败: rc=$RC http=$Q_HTTP offset=$OFFSET size=$SIZE attempt=$ATT" >&2
    sed -n '1,160p' /tmp/qdr_upsert.json >&2 || true
    if [ $ATT -ge 3 ]; then
      echo "[RESTORE] upsert 多次重试仍失败，终止" >&2
      exit 1
    fi
    sleep $(( ATT * 2 ))
    ATT=$(( ATT + 1 ))
  done
  # 基本校验：检查返回状态
  if ! jq -e '.status=="ok"' /tmp/qdr_upsert.json >/dev/null 2>&1; then
    echo "[RESTORE] upsert 返回非 ok：" >&2
    sed -n '1,160p' /tmp/qdr_upsert.json >&2 || true
    exit 1
  fi
  # 以本批过滤后文本数作为增量计数
  CNT=$(echo "$FS" | jq 'length')
  TOTAL=$(( TOTAL + CNT ))
  echo "[RESTORE] 本批写入 $CNT 条，累计 $TOTAL"

  OFFSET=$(( OFFSET + SIZE ))

done

echo "[RESTORE] 完成，共恢复 $TOTAL 条到 $COLL"
