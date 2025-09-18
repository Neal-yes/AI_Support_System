#!/usr/bin/env bash
set -euo pipefail

# 触发固定失败以尝试打开熔断的小脚本（不强行断言 CI 失败，仅用于观测）
# 环境变量：
# - API_BASE (默认 http://127.0.0.1:8000)
# - TENANT (默认 default)
# - TOOL_TYPE (默认 http_get)
# - TOOL_NAME (默认 simple)
# - URL_FAIL (默认 https://invalid.invalid/)
# - THRESHOLD (默认 1)
# - COOLDOWN_MS (默认 5000)
# - TIMES (默认 3)
# - TIMEOUT_S (默认 2)

API_BASE=${API_BASE:-http://127.0.0.1:8000}
TENANT=${TENANT:-default}
TOOL_TYPE=${TOOL_TYPE:-http_get}
TOOL_NAME=${TOOL_NAME:-simple}
URL_FAIL=${URL_FAIL:-https://invalid.invalid/}
THRESHOLD=${THRESHOLD:-1}
COOLDOWN_MS=${COOLDOWN_MS:-5000}
TIMES=${TIMES:-3}
TIMEOUT_S=${TIMEOUT_S:-2}

body(){
  jq -n --arg t "$TENANT" --arg tt "$TOOL_TYPE" --arg tn "$TOOL_NAME" --arg url "$URL_FAIL" \
        --argjson th "$THRESHOLD" --argjson cd "$COOLDOWN_MS" '{
    tenant_id:$t, tool_type:$tt, tool_name:$tn,
    params:{url:$url},
    options:{ retry_max:0, timeout_ms:800, circuit_threshold:$th, circuit_cooldown_ms:$cd, allow_hosts:["invalid.invalid"] }
  }'
}

echo "[CIRCUIT] firing TIMES=$TIMES threshold=$THRESHOLD cooldown_ms=$COOLDOWN_MS url=$URL_FAIL" >&2

for i in $(seq 1 "$TIMES"); do
  b=$(body)
  http=$(curl -sS -o /tmp/circuit_probe_${i}.json -w "%{http_code}" --connect-timeout 2 --max-time "$TIMEOUT_S" \
    -H 'Content-Type: application/json' -d "$b" "$API_BASE/api/v1/tools/invoke" || true)
  echo "[CIRCUIT] try=$i http=$http" >&2
  sed -n '1,2p' "/tmp/circuit_probe_${i}.json" >&2 || true
  sleep 0.3
done

echo "[CIRCUIT] done" >&2
