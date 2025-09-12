#!/usr/bin/env bash
set -euo pipefail

# 并发突发触发工具网关限流（rate limit）的小脚本
# 仅依赖 curl，默认对本地 API 进行 10 并发请求。
# 环境变量：
# - API_BASE (默认 http://127.0.0.1:8000)
# - TENANT (默认 default)
# - TOOL_TYPE (默认 http_get)
# - TOOL_NAME (默认 simple)
# - URL (默认 https://httpbin.org/get)
# - RATE_LIMIT (默认 2) —— 作为请求 options.rate_limit_per_sec
# - CONCURRENCY (默认 10)
# - TIMEOUT_S (默认 3) —— 单请求最大耗时

API_BASE=${API_BASE:-http://127.0.0.1:8000}
TENANT=${TENANT:-default}
TOOL_TYPE=${TOOL_TYPE:-http_get}
TOOL_NAME=${TOOL_NAME:-simple}
URL=${URL:-https://httpbin.org/get}
RATE_LIMIT=${RATE_LIMIT:-2}
CONCURRENCY=${CONCURRENCY:-10}
TIMEOUT_S=${TIMEOUT_S:-3}

body_template(){
  jq -n --arg t "$TENANT" --arg tt "$TOOL_TYPE" --arg tn "$TOOL_NAME" --arg url "$URL" --argjson rl "$RATE_LIMIT" '{
    tenant_id:$t, tool_type:$tt, tool_name:$tn,
    params:{url:$url}, options:{ rate_limit_per_sec:$rl, retry_max:0, timeout_ms:2000, allow_hosts:["httpbin.org"] }
  }'
}

req(){
  local body
  body=$(body_template)
  curl -sS --connect-timeout 2 --max-time "$TIMEOUT_S" \
    -H 'Content-Type: application/json' \
    -d "$body" \
    "$API_BASE/api/v1/tools/invoke" > /dev/null || true
}

export -f req body_template

# 生成 N 行占位并发执行
seq 1 "$CONCURRENCY" | xargs -I{} -P "$CONCURRENCY" bash -c 'req'

echo "[RATE-LIMIT] burst done: concurrency=$CONCURRENCY rate_limit_per_sec=$RATE_LIMIT url=$URL" >&2
