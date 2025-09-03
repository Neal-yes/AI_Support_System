# CI Metrics & Reports Index

This directory documents CI verification evidence and how to validate metrics locally. Files are referenced from the repo path `artifacts/metrics/`.

## Evidence Files (current repo)

- artifacts/metrics/rag_eval.csv
- artifacts/metrics/rag_eval.json
- artifacts/metrics/smoke_summary.md
- artifacts/metrics/tools_summary.md
- artifacts/metrics/tools_summary.json
- artifacts/metrics/api_metrics.prom
- artifacts/metrics/metrics_rag_probe.txt
- artifacts/metrics/metrics_after_404.prom
- artifacts/metrics/prom_tools_q1.json .. prom_tools_q7.json
- artifacts/metrics/prom_download_q1.json .. prom_download_q5.json
- artifacts/metrics/ask_plain.json / ask_plain.status
- artifacts/metrics/ask_rag.json / ask_rag.status
- artifacts/metrics/embedding_upsert.json
- artifacts/metrics/alertmanager_active_alerts.json
- artifacts/metrics/grafana_active_alerts.json
- artifacts/metrics/grafana_alert_rules.png
- artifacts/metrics/grafana_alert_detail.png

## What to Verify

- RAG gate metrics
  - File(s): `rag_eval.csv`, `rag_eval.json`
  - Check thresholds: hit_ratio >= 0.60, avg_top1 >= 0.35 (or project-configured values)
- Smoke ask results
  - File(s): `smoke_summary.md`, `ask_plain.json`, `ask_rag.json`
  - Expect both plain and RAG smoke to succeed with non-empty outputs
- Tools gateway probes
  - File(s): `tools_summary.*`, `prom_tools_q*.json`
  - Confirm rate limiting, retries, and circuit metrics recorded when triggered
- Download/export probes
  - File(s): `prom_download_q*.json`, `metrics_after_404.prom`
  - Validate download metrics counters/histograms increment; 404 handled
- Prometheus scrape snapshot
  - File(s): `api_metrics.prom`, `metrics_rag_probe.txt`
  - Confirm `tools_*`, `rag_*`, `http_*` metrics are present
- Alerting
  - File(s): `alertmanager_active_alerts.json`, `grafana_active_alerts.json`, PNG screenshots
  - Confirm alert rules exist and sample alerts can be observed

## Quick Local Checks

- Show core metrics lines:
  ```bash
  curl -s http://localhost:8000/metrics | egrep '^(# (HELP|TYPE) (tools_|rag_|http_)|tools_|rag_|http_)' | head -n 80
  ```
- RAG eval (JSON):
  ```bash
  curl -s -X POST http://localhost:8000/chat/rag_eval \
    -H 'Content-Type: application/json' \
    -d '{"queries":["如何登录？","忘记密码怎么办？"],"collection":"demo","top_k":3}' | jq .
  ```
- Smoke ask:
  ```bash
  bash scripts/smoke_ask.sh
  ```

## Frontend E2E (Playwright)

- Local run (in `frontend/`):
  ```bash
  npm install
  npx playwright install chromium
  npm run test:e2e   # auto build, start preview on :5177 and run tests
  # headed debug:
  npm run e2e:headed
  ```

- What is covered:
  - 观测表单非法/合法 URL 校验与按钮 title 提示
  - 生成的指标/日志跳转链接参数正确（拦截 window.open 断言）
  - 导入 `docs/assets/toolsObsConf.json` 后字段回填与按钮联动
  - 导出配置 JSON 内容正确（拦截下载、解析并断言 promBase/logsBase/模板/version/exportedAt）

- Files:
  - `frontend/playwright.config.ts`
  - `frontend/tests/e2e/tools-obs.spec.ts`

- CI integration:
  - GitHub Actions job `frontend-e2e` 安装依赖与浏览器并运行 `npm run test:e2e`
  - 开启多浏览器（Chromium、Firefox、WebKit）并收集截图、视频与 trace
  - 失败时上传 `frontend/playwright-report`（含 HTML 报告、视频、trace）便于排查

## Notes

- The CI artifact `ci_step_summary.md` from GitHub Actions is not committed here. Keep a copy of the latest summary in release notes or attach the Actions run link during reviews.
- For full reproducibility, see `README.md` sections: API quick start, RAG evaluation, metrics & alerts.
 - WebKit 兼容性：部分输入框在折叠区域内可能被判定为 hidden。E2E 用例已通过以下策略增强稳定性：
   - 优先执行 `scrollIntoViewIfNeeded()` 并断言 `toBeVisible()`；
   - 若仍不可见，则回退为在页面环境内直接设置值并触发 `input/change` 事件，以确保表单状态正确更新并可被导出。
