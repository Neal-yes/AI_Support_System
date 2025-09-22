# 备份 / 恢复运行手册（Runbook）

更新时间：2025-09-22 (+08:00)

本手册记录一次端到端“备份 → 恢复 → 校验”的标准操作流程与注意事项，建议在隔离环境执行，并将关键产出物（日志、截图、校验结果）归档至 `artifacts/metrics/` 或发布页说明。

---

## 目标与范围
- 覆盖对象：Qdrant 默认集合（或指定集合）向量与 payload。
- 产出与沉淀：
  - 备份 JSON（例如：`artifacts/metrics/qdrant_backup_<collection>.json`）。
  - 恢复脚本执行日志、时间开销（RTO 参考）。
  - 恢复后抽样检索与指标校验结果。

---

## 先决条件
- 服务已启动：`docker compose up -d`（API/DB/Redis/Qdrant/Ollama）。
- Prometheus/Grafana 可选但建议同时启动，便于记录指标。
- 准备环境变量（如需）：
  ```bash
  export RAG_COLLECTION=default_collection
  ```

---

## 步骤一：备份（Backup）
1. 执行脚本：
   ```bash
   bash scripts/ci/backup_qdrant_collection.sh
   ```
2. 关键输出：
   - 备份文件：`artifacts/metrics/qdrant_backup_${RAG_COLLECTION}.json`
   - 可选：将执行时长与条目数量写入 `artifacts/metrics/ci_summary.txt`

3. 初步校验：
   ```bash
   ls -lh artifacts/metrics/qdrant_backup_${RAG_COLLECTION}.json
   jq -r '.[0:3]' artifacts/metrics/qdrant_backup_${RAG_COLLECTION}.json | wc -l
   ```

---

## 步骤二：恢复（Restore）
1. 设定目标集合（可恢复到新集合便于对比）：
   ```bash
   export RAG_COLLECTION=default_collection_restored
   export BACKUP_JSON=artifacts/metrics/qdrant_backup_default_collection.json
   ```
2. 执行脚本：
   ```bash
   bash scripts/ci/restore_qdrant_collection.sh
   ```
3. 关注输出：
   - upsert 成功条数与耗时。
   - 错误统计（如维度不匹配将被明确记录）。

---

## 步骤三：恢复后校验（Validation）
1. 指标校验：
   ```bash
   curl -s http://localhost:8000/metrics | egrep 'import_duration_seconds|import_rows_total|import_batches_total|import_skipped_total' | head
   ```
2. 抽样检索：
   ```bash
   curl -s http://localhost:8000/embedding/search \
     -H 'Content-Type: application/json' \
     -d '{"query":"登录","collection":"default_collection_restored","top_k":3}' | jq .
   ```
3. RAG 预检（可选）：
   ```bash
   curl -s -X POST http://localhost:8000/api/v1/rag/preflight \
     -H 'Content-Type: application/json' \
     -d '{"query":"登录","collection":"default_collection_restored","top_k":3}' | jq .
   ```

---

## RTO/RPO 记录
- RTO（恢复时间目标）：记录从开始执行 `restore_qdrant_collection.sh` 到检索可用的总时长（秒）。
- RPO（数据恢复点目标）：记录与备份时刻的最大数据偏移（通常为 0，如只读演练）。

建议将统计写入：`artifacts/metrics/ci_summary.txt`，同时在 README 的 “Backup Signals” 小节自动注入。

---

## 常见问题与排查
- 小集合在“取消导出/导入”测试时可能秒级完成，建议提高 `delay_ms_per_point` 或扩大样本量再测试。
- 维度不匹配：确保恢复时使用与原集合一致的嵌入模型/维度；优先使用导出原文直接恢复。
- 指标观测：`GET /metrics` 暴露导入/导出相关直方图与计数，必要时延长抓取/评估窗口。

---

## 附：一次演练结果记录（模板）
- 时间：2025-09-__
- 源集合：`default_collection`
- 目标集合：`default_collection_restored`
- 备份文件大小：__ MB
- 恢复条目数：__
- RTO：__ 秒
- 抽样检索示例响应：见 `download_artifacts/<RUN_ID>/...`
- 指标截图：Grafana 面板链接/截图路径
