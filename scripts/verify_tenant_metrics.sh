#!/usr/bin/env bash
set -euo pipefail
set -x

TENANT="${1:-demo}"
API_BASE="http://localhost:${API_PORT:-8000}"
PROM="http://localhost:9090"

COL="default_collection"

# 输出目录（用于 CI artifacts）
OUT_DIR="artifacts/metrics"
mkdir -p "${OUT_DIR}"

echo "0) Ensure collection '${COL}' exists (vector_size=1)"
curl -fsS -X POST "${API_BASE}/collections/ensure" \
  -H "Content-Type: application/json" \
  -d '{"name":"'"${COL}"'","vector_size":1}' >/dev/null || true

echo "0.x) Verify collection exists (retry until ready)"
# 等待集合可用（API 需要 Qdrant 就绪）。最多重试 12 次 * 5s = 60s。
COL_HTTP=""
for i in {1..12}; do
  COL_HTTP=$(curl -sS -o /dev/null -w "%{http_code}" "${API_BASE}/collections/${COL}" || true)
  if [ "${COL_HTTP}" = "200" ]; then
    echo "Collection '${COL}' is ready (HTTP 200)"
    break
  fi
  echo "Collection not ready yet (http=${COL_HTTP}), retrying in 5s..."
  sleep 5
done
if [ "${COL_HTTP:-}" != "200" ]; then
  echo "Collection '${COL}' not ready after retries; aborting."
  exit 1
fi

echo "0.1) Insert one demo point (no embeddings required)"
# 生成带真实换行的 NDJSON 文本
JSONL_LINE='{"id":1,"vector":[0.1],"payload":{"tag":"demo"}}'
JSONL_CONTENT=$(printf '%s\n' "$JSONL_LINE")

# 构造合法 JSON 请求体（优先使用 jq，若无则回退到 python3）
if command -v jq >/dev/null 2>&1; then
  REQ_BODY=$(jq -nc \
    --arg col "$COL" \
    --arg jsonl "$JSONL_CONTENT" \
    '{collection:$col, jsonl:$jsonl, continue_on_error:false, batch_size:1000, on_conflict:"upsert"}')
else
  REQ_BODY=$(python3 - <<'PY'
import json, os
col = os.environ.get('COL', 'default_collection')
jsonl = '{"id": 1, "vector": [0.1], "payload": {"tag": "demo"}}\n'
print(json.dumps({
  "collection": col,
  "jsonl": jsonl,
  "continue_on_error": False,
  "batch_size": 1000,
  "on_conflict": "upsert",
}))
PY
)
fi

echo "0.2) Import one row via /collections/import"
HTTP_CODE=$(curl -sS -o /tmp/import_resp.json -w "%{http_code}" -X POST "${API_BASE}/collections/import" \
  -H "Content-Type: application/json" \
  -d "$REQ_BODY") || true
if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
  echo "Import failed: HTTP $HTTP_CODE"
  echo "Response body:"; sed -n '1,200p' /tmp/import_resp.json || true
  exit 1
fi
echo "Import OK (HTTP $HTTP_CODE)"

echo "1) Trigger first download with tenant: ${TENANT} (and verify rows)"
curl -fsS -H "X-Tenant-Id: ${TENANT}" \
  "${API_BASE}/collections/export/download?collection=${COL}&with_vectors=true&with_payload=true&gzip=false" \
  -o /tmp/download1.jsonl
ROWS1=$(wc -l </tmp/download1.jsonl | tr -d ' ')
echo "Downloaded rows: $ROWS1"

echo "Waiting for Prometheus to scrape once (20s)..."
sleep 20

echo "1.1) Trigger second download with tenant: ${TENANT}"
curl -fsS -H "X-Tenant-Id: ${TENANT}" \
  "${API_BASE}/collections/export/download?collection=${COL}&with_vectors=true&with_payload=true&gzip=false" \
  -o /dev/null || true

echo "Waiting for Prometheus to scrape again (20s)..."
sleep 20

echo "1.2) Trigger third download with tenant: ${TENANT}"
curl -fsS -H "X-Tenant-Id: ${TENANT}" \
  "${API_BASE}/collections/export/download?collection=${COL}&with_vectors=true&with_payload=true&gzip=false" \
  -o /dev/null || true

echo "Waiting for Prometheus to scrape again (20s)..."
sleep 20

echo "2) Query Prometheus for download metrics with tenant filter"

# 定义查询
QUERY1='sum by (tenant,collection) (rate(download_bytes_total{tenant="'"${TENANT}"'"}[1m]))'
QUERY2='histogram_quantile(0.95, sum by (le) (rate(download_duration_seconds_bucket{tenant="'"${TENANT}"'"}[5m])))'
QUERY3='sum by (tenant,collection) (download_rows_total{tenant="'"${TENANT}"'"})'
QUERY4='sum by (tenant,collection) (download_duration_seconds_count{tenant="'"${TENANT}"'"})'
QUERY5='export_success_rate{tenant="'"${TENANT}"'"}'

IDX=1
for Q in "$QUERY1" "$QUERY2" "$QUERY3" "$QUERY4" "$QUERY5"; do
  echo "Query: $Q"
  curl -fsS --get "${PROM}/api/v1/query" --data-urlencode "query=${Q}" \
    | tee "${OUT_DIR}/prom_download_q${IDX}.json" \
    | jq .
  IDX=$((IDX+1))
done

echo "3) Tools Gateway: 通过 /api/v1/tools/invoke 触发 tools_* 指标"

# 3.1 基本请求 + 缓存命中（同键两次，第二次应命中缓存）
echo "3.1) cache hit 演示"
REQ_TOOLS_BASE='{"tenant_id":"'"${TENANT}"'","tool_type":"http_get","tool_name":"simple","params":{"url":"https://example.com"},"options":{"timeout_ms":2000}}'
curl -fsS -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_BASE" -o /dev/null || true
REQ_TOOLS_CACHE='{"tenant_id":"'"${TENANT}"'","tool_type":"http_get","tool_name":"simple","params":{"url":"https://example.com"},"options":{"timeout_ms":2000,"cache_ttl_ms":10000}}'
curl -fsS -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_CACHE" -o /dev/null || true
curl -fsS -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_CACHE" -o /dev/null || true

# 3.2 限流 429（将每秒限额设为1，在同一秒内快速请求2次）
echo "3.2) rate limit 429 演示"
REQ_TOOLS_RL='{"tenant_id":"'"${TENANT}"'","tool_type":"http_get","tool_name":"simple","params":{"url":"https://example.com"},"options":{"timeout_ms":1000,"rate_limit_per_sec":1}}'
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_RL" || true
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_RL" || true

# 3.3 模拟失败 + 熔断（阈值=1，首次失败后立即打开熔断；随后同键再次调用应被 503 拦截）
echo "3.3) fail + circuit open 演示"
REQ_TOOLS_FAIL='{"tenant_id":"'"${TENANT}"'","tool_type":"http_get","tool_name":"simple","params":{"url":"https://example.com"},"options":{"timeout_ms":1000,"simulate_fail":true,"circuit_threshold":1,"circuit_cooldown_ms":5000}}'
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_FAIL" || true
# 同键再次调用，预计触发熔断 open
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_FAIL" || true

# 3.4 重试计数（模拟失败 + retry_max=2，应观察到 retries 增加）
echo "3.4) retries 演示"
REQ_TOOLS_RETRY='{"tenant_id":"'"${TENANT}"'","tool_type":"http_post","tool_name":"simple","params":{"url":"https://example.com","body":{"k":"v"}},"options":{"timeout_ms":1000,"simulate_fail":true,"retry_max":2,"retry_backoff_ms":50}}'
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_RETRY" || true

echo "等待 Prometheus 抓取一次 (20s)，随后再次触发重试以形成 1m 窗口的增量"
sleep 20
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${API_BASE}/api/v1/tools/invoke" -H "Content-Type: application/json" -d "$REQ_TOOLS_RETRY" || true

echo "再次等待 Prometheus 抓取 (20s)..."
sleep 20

echo "3.x) 查询 Prometheus: tools_* 与录制规则"
Q_T1='sum by (tenant,tool_type,tool_name) (increase(tools_requests_total[1m]))'
Q_T2='sum by (tenant,tool_type,tool_name) (increase(tools_errors_total[1m]))'
Q_T3='sum by (tenant,tool_type,tool_name) (increase(tools_rate_limited_total[1m]))'
Q_T4='sum by (tenant,tool_type,tool_name) (increase(tools_circuit_open_total[5m]))'
Q_T5='sum by (tenant,tool_type,tool_name) (increase(tools_cache_hit_total[1m]))'
Q_T6='sum by (tenant,tool_type,tool_name) (increase(tools_retries_total[1m]))'
Q_T7='tools_error_ratio_1m{tenant="'"${TENANT}"'"}'
TIDX=1
for Q in "$Q_T1" "$Q_T2" "$Q_T3" "$Q_T4" "$Q_T5" "$Q_T6" "$Q_T7"; do
  echo "Query: $Q"
  curl -fsS --get "${PROM}/api/v1/query" --data-urlencode "query=${Q}" \
    | tee "${OUT_DIR}/prom_tools_q${TIDX}.json" \
    | jq .
  TIDX=$((TIDX+1))
done

# 额外证据：API /metrics 快照与 Prometheus 目标状态
echo "3.y) 保存 API /metrics 与 Prometheus targets 快照"
curl -fsS "${API_BASE}/metrics" -o "${OUT_DIR}/api_metrics.prom" || true
curl -fsS --get "${PROM}/api/v1/targets" -o "${OUT_DIR}/prom_targets.json" || true

# 可选：Grafana 告警（需要匿名访问或提供认证）
# 新版 API：规则列表 /api/alert-rules；活动告警 /api/alertmanager/grafana/api/v2/alerts
if curl -sS -o /dev/null -w "%{http_code}" "http://localhost:3000/login" | grep -Eq "^(200|302)$"; then
  if [[ -n "${GRAFANA_AUTH:-}" ]]; then
    curl -fsS -u "${GRAFANA_AUTH}" "http://localhost:3000/api/alert-rules" -o "${OUT_DIR}/grafana_alert_rules.json" || true
    curl -fsS -u "${GRAFANA_AUTH}" "http://localhost:3000/api/alertmanager/grafana/api/v2/alerts" -o "${OUT_DIR}/grafana_active_alerts.json" || true
  else
    curl -fsS "http://localhost:3000/api/alert-rules" -o "${OUT_DIR}/grafana_alert_rules.json" || true
    curl -fsS "http://localhost:3000/api/alertmanager/grafana/api/v2/alerts" -o "${OUT_DIR}/grafana_active_alerts.json" || true
  fi
fi

echo "Done."
