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

# 等待 API 关键依赖就绪（Qdrant + Ollama），避免启动竞态
wait_api_ready() {
  local max_wait=${1:-60}
  local start_ts=$(date +%s)
  local url="${API_BASE}/-/ready"
  echo "[EMBED PREP] 等待 API 就绪: $url (最长 ${max_wait}s)"
  while true; do
    local code
    code=$(curl -sS -o /tmp/ready.json -w "%{http_code}" "$url" || true)
    if [ "$code" = "200" ] && jq -e '.status == "ok" or .status == "degraded"' /tmp/ready.json >/dev/null 2>&1; then
      # degraded 也可接受（有时 Redis/Postgres 非关键）
      echo "[EMBED PREP] API 已就绪 (code=$code)"
      break
    fi
    local now=$(date +%s)
    if [ $(( now - start_ts )) -ge $max_wait ]; then
      echo "[EMBED PREP] 等待 API 就绪超时 (code=$code)，继续尝试 upsert（将带重试）" >&2
      break
    fi
    sleep 2
  done
}

# 预热嵌入模型，避免首次请求时模型下载/加载导致 500
warmup_embed() {
  local max_attempts=${1:-8}
  local texts='{"texts":["warmup"]}'
  local body="$texts"
  # 若显式指定嵌入模型，附带到 body
  if [ -n "${RAG_MODEL}" ]; then
    body=$(jq -n --argjson texts '["warmup"]' --arg model "${RAG_MODEL}" '{texts: $texts, model: $model}')
  fi
  echo "[EMBED PREP] 预热嵌入模型（最多 ${max_attempts} 次）"
  local attempt=1
  local backoff=1
  while true; do
    set +e
    local code
    code=$(curl -sS -o /tmp/embed_warmup.json -w "%{http_code}" \
      -H 'Content-Type: application/json' \
      -d "$body" \
      "${API_BASE}/embedding/embed")
    local rc=$?
    set -e
    if [ $rc -eq 0 ] && [ "$code" = "200" ]; then
      local dim
      dim=$(jq -r '.dimension // 0' /tmp/embed_warmup.json 2>/dev/null || echo 0)
      echo "[EMBED PREP] 嵌入模型预热成功（dim=$dim）"
      break
    fi
    echo "[EMBED PREP] 嵌入预热失败: rc=$rc http=$code attempt=$attempt" >&2
    if [ $attempt -ge $max_attempts ]; then
      echo "[EMBED PREP] 嵌入预热重试耗尽，继续后续 upsert（upsert 自身也有重试）" >&2
      sed -n '1,200p' /tmp/embed_warmup.json >&2 || true
      break
    fi
    sleep $backoff
    attempt=$(( attempt + 1 ))
    if [ $backoff -lt 10 ]; then backoff=$(( backoff * 2 )); fi
  done
}

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
  echo "未从 $SRC_JSONL 提取到有效文本，尝试回退..." >&2
  # Prefer demo.jsonl(.gz) first; avoid retrying the same file as current SRC_JSONL
  choose_fallback() {
    local current="$1"
    # ordered candidates
    local cands=("demo.jsonl" "demo.jsonl.gz" "demo_faq.jsonl" "demo_faq.jsonl.gz")
    for cand in "${cands[@]}"; do
      # skip if identical to current
      if [ "$cand" = "$current" ]; then
        continue
      fi
      if [ -f "$cand" ]; then
        if [[ "$cand" == *.gz ]]; then
          local unz="${cand%.gz}"
          echo "发现 $cand，解压生成 $unz"
          gunzip -c "$cand" > "$unz"
          echo "$unz"
          return 0
        else
          echo "$cand"
          return 0
        fi
      fi
    done
    return 1
  }

  fb=$(choose_fallback "$SRC_JSONL") || {
    echo "仍未找到可用评测源文件" >&2
    exit 2
  }
  SRC_JSONL="$fb"
  echo "使用回退源: $SRC_JSONL"

  # 重新提取文本与简要 payload（如 tag/question/answer）
  TMP_JSON=$(mktemp)
  awk 'NR<='"${MAX_DOCS}"' {print}' "$SRC_JSONL" \
    | jq -s '[ .[] | { text: (.question // .query // .prompt // .text // ""), payload: { tag: (.tag // null), question: (.question // .query // .prompt // null), answer: (.answer // null) } } | select(.text != "") ]' > "$TMP_JSON"

  COUNT=$(jq 'length' "$TMP_JSON")
  if [ "$COUNT" = "0" ]; then
    echo "仍未提取到文本，改用内置小语料以初始化向量库..." >&2
    TMP_JSON=$(mktemp)
    jq -n '[
      {text:"如何查看 Prometheus 指标?", payload:{tag:"faq", text:"如何查看 Prometheus 指标?", question:"如何查看 Prometheus 指标?", answer:null}},
      {text:"本地 AI 客服系统如何工作?", payload:{tag:"faq", text:"本地 AI 客服系统如何工作?", question:"本地 AI 客服系统如何工作?", answer:null}},
      {text:"如何导入示例数据?", payload:{tag:"faq", text:"如何导入示例数据?", question:"如何导入示例数据?", answer:null}},
      {text:"如何进行 RAG 检索?", payload:{tag:"faq", text:"如何进行 RAG 检索?", question:"如何进行 RAG 检索?", answer:null}},
      {text:"如何排查 500 错误?", payload:{tag:"faq", text:"如何排查 500 错误?", question:"如何排查 500 错误?", answer:null}}
    ]' > "$TMP_JSON"
    COUNT=$(jq 'length' "$TMP_JSON")
  fi
fi

echo "[EMBED PREP] 将写入 ${COUNT} 条到 Qdrant（batch=${BATCH_SIZE} collection=${RAG_COLLECTION:-<default>} model=${RAG_MODEL:-<default>}）"

OFFSET=0
TOTAL_UPSERT=0
SUMMARY_JSON="${OUT_DIR}/embedding_upsert.json"
echo '{}' > "$SUMMARY_JSON"

# 先等待 API/-/ready（带超时），提升稳定性
wait_api_ready 90

# 预热嵌入模型，减少首次 upsert 出错概率
warmup_embed 8
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

  # 带指数退避的重试（最多 8 次）
  attempt=1
  max_attempts=8
  backoff=1
  while true; do
    set +e
    HTTP_CODE=$(curl -sS -o /tmp/upsert_resp.json -w "%{http_code}" \
      -H 'Content-Type: application/json' \
      -d "$BODY" \
      "${API_BASE}/embedding/upsert")
    RC=$?
    set -e
    if [ $RC -eq 0 ] && [ "$HTTP_CODE" = "200" ]; then
      break
    fi
    echo "[EMBED PREP] upsert 尝试失败: rc=$RC http=$HTTP_CODE offset=$OFFSET size=$SIZE attempt=$attempt" >&2
    # 对 500/502/503/504 或连接错误做重试
    if [ $attempt -ge $max_attempts ]; then
      echo "[EMBED PREP] upsert 重试耗尽，失败退出" >&2
      sed -n '1,200p' /tmp/upsert_resp.json >&2 || true
      # persist response for diagnostics
      cp -f /tmp/upsert_resp.json "$OUT_DIR/upsert_resp.json" 2>/dev/null || true
      exit 1
    fi
    sleep $backoff
    attempt=$(( attempt + 1 ))
    # 增加退避但设上限
    if [ $backoff -lt 10 ]; then backoff=$(( backoff * 2 )); fi
  done

  CNT=$(jq -r '.count // 0' /tmp/upsert_resp.json)
  TOTAL_UPSERT=$(( TOTAL_UPSERT + CNT ))
  echo "[EMBED PREP] upsert 成功，本批 $CNT 条，累计 $TOTAL_UPSERT"

  OFFSET=$(( OFFSET + SIZE ))
done

jq -n --arg total "$TOTAL_UPSERT" --arg src "$SRC_JSONL" --arg coll "${RAG_COLLECTION}" '{total: ($total|tonumber), src: $src, collection: $coll}' > "$SUMMARY_JSON"

echo "[EMBED PREP] finished. total_upsert=$TOTAL_UPSERT summary=$SUMMARY_JSON"
