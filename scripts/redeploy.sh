#!/usr/bin/env bash
set -euo pipefail

# 1) Rebuild API to include new deps (PyJWT) and latest code
docker compose build api
# Start/refresh API container
docker compose up -d api

# 2) Restart Prometheus to reload rules
# (prometheus in this compose does not expose HTTP reload)
docker compose restart prometheus

# 3) Restart Grafana to apply provisioning changes (dashboards/variables)
docker compose restart grafana

# 4) Optional: restart alertmanager if you changed alertmanager.yml
# docker compose restart alertmanager

echo "Done. Waiting 10s for services to stabilize..."
sleep 10

docker compose ps
