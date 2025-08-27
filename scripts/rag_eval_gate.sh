#!/usr/bin/env bash
set -euo pipefail

# RAG 评测门禁脚本
# - 调用后端 /chat/rag_eval，生成 JSON 与 CSV 报告
# - 依据阈值判定是否通过：
#   * 命中率 >= GATE_HIT_RATIO_MIN（默认 0.65）
#   * 平均 top1 分数 >= GATE_AVG_TOP1_MIN（默认 0.35）
#   * 判断模式：GATE_STRICT=both（需同时满足）或 either（满足其一即可）
#   * 可设最小样本量：GATE_MIN_TOTAL（默认 10）；是否强制：GATE_REQUIRE_MIN_TOTAL（0/1）
# - 可通过环境变量覆盖：
#   * API_BASE=http://localhost:8000
#   * RAG_COLLECTION=default（由后端 settings.QDRANT_COLLECTION 决定）
#   * RAG_TOP_K=5
#   * RAG_EVAL_QUERIES=demo_faq.jsonl（每行 JSON，字段 question）
#   * GATE_HIT_RATIO_MIN=0.65
#   * GATE_AVG_TOP1_MIN=0.35
#   * GATE_STRICT=both  # both|either
#   * GATE_MIN_TOTAL=10
#   * GATE_REQUIRE_MIN_TOTAL=0
#   * RAG_EXPORT_CSV=1（是否输出 CSV 报告）

API_BASE=${API_BASE:-http://localhost:8000}
RAG_COLLECTION=${RAG_COLLECTION:-}
RAG_TOP_K=${RAG_TOP_K:-5}
RAG_EVAL_QUERIES=${RAG_EVAL_QUERIES:-demo_faq.jsonl}
RAG_MODEL=${RAG_MODEL:-}
GATE_HIT_RATIO_MIN=${GATE_HIT_RATIO_MIN:-0.65}
GATE_AVG_TOP1_MIN=${GATE_AVG_TOP1_MIN:-0.35}
GATE_STRICT=${GATE_STRICT:-both}
GATE_MIN_TOTAL=${GATE_MIN_TOTAL:-10}
GATE_REQUIRE_MIN_TOTAL=${GATE_REQUIRE_MIN_TOTAL:-0}
RAG_EXPORT_CSV=${RAG_EXPORT_CSV:-1}

OUT_DIR=${OUT_DIR:-artifacts/metrics}
mkdir -p "$OUT_DIR"

have_jq() { command -v jq >/dev/null 2>&1; }

if ! have_jq; then
  echo "jq 未安装，请先安装 jq" >&2
  exit 2
fi

# 组装 queries 数组
QUERIES_JSON=""
if [ -f "$RAG_EVAL_QUERIES" ]; then
  # 从 JSONL 文件中提取问题字段，最多取 50 条；兼容 text 作为问题
  QUERIES_JSON=$(awk 'NR<=50 {print}' "$RAG_EVAL_QUERIES" | jq -s '[ .[] | .question // .query // .prompt // .text | select(type=="string") ]')
  # 如果文件存在但未提取到任何问题，则回退到内置 queries
  if [ -z "$QUERIES_JSON" ] || [ "$(echo "$QUERIES_JSON" | jq 'length')" = "0" ]; then
    echo "[RAG GATE] 提供的 $RAG_EVAL_QUERIES 中未找到可用 queries，使用内置样例" >&2
    QUERIES_JSON='["如何启动本地服务?","如何查看 Prometheus 指标?","如何触发 E2E 工作流?","如何导入 FAQ 数据?","如何使用 RAG 进行问答?"]'
  fi
else
  # 兜底内置样例
  QUERIES_JSON='["如何启动本地服务?","如何查看 Prometheus 指标?","如何触发 E2E 工作流?","如何导入 FAQ 数据?","如何使用 RAG 进行问答?"]'
fi

BODY=$(jq -n \
  --argjson queries "$QUERIES_JSON" \
  --arg coll "${RAG_COLLECTION}" \
  --argjson topk "${RAG_TOP_K}" \
  --arg model "${RAG_MODEL}" '
  {
    queries: $queries,
    top_k: ($topk | tonumber)
  }
  + (if $coll == "" then {} else {collection: $coll} end)
  + (if $model == "" then {} else {model: $model} end)
')

echo "[RAG GATE] 调用: ${API_BASE}/chat/rag_eval top_k=${RAG_TOP_K} collection=${RAG_COLLECTION:-<default>}"
JSON_OUT="${OUT_DIR}/rag_eval.json"
CSV_OUT="${OUT_DIR}/rag_eval.csv"

set +e
HTTP_CODE=$(curl -sS -o "$JSON_OUT" -w "%{http_code}" \
  -H 'Content-Type: application/json' \
  -d "$BODY" \
  "${API_BASE}/chat/rag_eval")
CURL_RC=$?
set -e

if [ $CURL_RC -ne 0 ] || [ "$HTTP_CODE" != "200" ]; then
  echo "调用 /chat/rag_eval 失败: rc=$CURL_RC http=$HTTP_CODE" >&2
  echo "响应内容：" >&2
  sed -n '1,200p' "$JSON_OUT" >&2 || true
  exit 1
fi

HIT_RATIO=$(jq -r '.summary.hit_ratio // 0' "$JSON_OUT")
AVG_TOP1=$(jq -r '.summary.avg_top1 // 0' "$JSON_OUT")
TOTAL=$(jq -r '.summary.total // 0' "$JSON_OUT")

echo "[RAG GATE] total=$TOTAL hit_ratio=$HIT_RATIO avg_top1=$AVG_TOP1"
echo "[RAG GATE] 阈值: hit_ratio>=${GATE_HIT_RATIO_MIN} ${GATE_STRICT} avg_top1>=${GATE_AVG_TOP1_MIN} (min_total=${GATE_MIN_TOTAL}, require_min_total=${GATE_REQUIRE_MIN_TOTAL})"

# 样本量校验
if [ "$GATE_REQUIRE_MIN_TOTAL" = "1" ] && awk -v t="$TOTAL" -v m="$GATE_MIN_TOTAL" 'BEGIN{ if (t+0 < m+0) exit 1 }'; then
  : # enough
elif [ "$GATE_REQUIRE_MIN_TOTAL" = "1" ]; then
  echo "[RAG GATE] FAIL: total($TOTAL) < required min_total($GATE_MIN_TOTAL)" >&2
  exit 3
elif awk -v t="$TOTAL" -v m="$GATE_MIN_TOTAL" 'BEGIN{ if (t+0 < m+0) exit 1 }'; then
  :
else
  echo "[RAG GATE] WARN: total($TOTAL) 小于建议最小样本量($GATE_MIN_TOTAL)，仅作提醒不阻断" >&2
fi

PASS=0
MET_HR=0
MET_AT1=0
awk -v hr="$HIT_RATIO" -v min="${GATE_HIT_RATIO_MIN}" 'BEGIN{ if (hr+0 >= min+0) exit 0; else exit 1 }' && MET_HR=1 || true
awk -v at1="$AVG_TOP1" -v min="${GATE_AVG_TOP1_MIN}" 'BEGIN{ if (at1+0 >= min+0) exit 0; else exit 1 }' && MET_AT1=1 || true

if [ "$GATE_STRICT" = "either" ]; then
  if [ $MET_HR -eq 1 ] || [ $MET_AT1 -eq 1 ]; then PASS=1; fi
else
  if [ $MET_HR -eq 1 ] && [ $MET_AT1 -eq 1 ]; then PASS=1; fi
fi

if [ "${RAG_EXPORT_CSV}" = "1" ]; then
  echo "[RAG GATE] 生成 CSV 报告..."
  set +e
  HTTP_CODE2=$(curl -sS -o "$CSV_OUT" -w "%{http_code}" \
    -H 'Content-Type: application/json' \
    -d "$(echo "$BODY" | jq '. + {export:"csv"}')" \
    "${API_BASE}/chat/rag_eval")
  set -e
  if [ "$HTTP_CODE2" != "200" ]; then
    echo "CSV 导出失败，http=$HTTP_CODE2（忽略，不阻断）" >&2
    rm -f "$CSV_OUT" || true
  fi
fi

# Generate markdown summary for Job Summary publishing
SUMMARY_MD="${OUT_DIR}/rag_gate_summary.md"
{
  echo "## RAG Eval Gate"
  echo
  echo "- total=${TOTAL} hit_ratio=${HIT_RATIO} avg_top1=${AVG_TOP1} top_k=${RAG_TOP_K}"
  echo "- thresholds: hit_ratio>=${GATE_HIT_RATIO_MIN} ${GATE_STRICT} avg_top1>=${GATE_AVG_TOP1_MIN} (min_total=${GATE_MIN_TOTAL} require_min_total=${GATE_REQUIRE_MIN_TOTAL})"
  if [ -f "$CSV_OUT" ]; then
    # Append the CSV summary footer if present
    echo
    echo "- csv: $(basename "$CSV_OUT")"
    # Try to print the summary line if exists (footer)
    tail -n 3 "$CSV_OUT" | sed -n '1,3p' || true
  fi
} > "$SUMMARY_MD" || true

# If not pass, include diagnostics from CSV: lowest top1_score and no-match samples
if [ $PASS -ne 1 ] && [ -f "$CSV_OUT" ]; then
  {
    echo
    echo "### Diagnostics"
    echo
    echo "- Lowest top1_score samples (up to 5):"
    # Skip header and possible footer, keep lines with 5 columns, then sort by 3rd column ascending numerically
    awk -F',' 'NR==1{next} $1!~/^collection$/ && NF>=5 {print}' "$CSV_OUT" | sort -t',' -k3,3g | head -n 5 | sed 's/^/  - /'
    echo
    echo "- No-match samples (up to 5):"
    awk -F',' 'NR==1{next} $2=="False" && NF>=5 {print "  - "$0}' "$CSV_OUT" | head -n 5
  } >> "$SUMMARY_MD" || true
fi

if [ $PASS -eq 1 ]; then
  echo "[RAG GATE] PASS"
  exit 0
else
  echo "[RAG GATE] FAIL: 未达标 -> hit_ratio(${HIT_RATIO}) vs ${GATE_HIT_RATIO_MIN}, avg_top1(${AVG_TOP1}) vs ${GATE_AVG_TOP1_MIN} (mode=${GATE_STRICT})"
  exit 3
fi
