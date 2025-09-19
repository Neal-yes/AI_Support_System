# 备份 / 恢复演练手册（Playbook）

更新时间：2025-09-15 15:05 (+08:00)

目的：提供可落地、可复用的 Qdrant 向量库与相关工件的备份/恢复方案与演练步骤，明确 RTO/RPO 目标与校验指引。

---

## 术语
- RTO（恢复时间目标）：≤ 15 分钟（开发/测试环境）。
- RPO（恢复点目标）：≤ 1 小时（定时备份频率可调）。

---

## 备份方案
- 对象：Qdrant 集合（含向量与 payload）、关键配置与评测工件。
- 工具/脚本：`scripts/ci/backup_qdrant_collection.sh`
- 建议频率：每小时一次；保留最近 N（默认 24）份。

### 手动备份
```bash
# 必要环境：QDRANT_URL（默认 http://localhost:6333）、COLLECTION
export COLLECTION=metrics_demo_1d
bash scripts/ci/backup_qdrant_collection.sh
```

### 产物位置
- 默认：`download/` 或 `download_artifacts/<timestamp>/`
- 归档：建议将最近一次备份同步到对象存储（可选）

---

## 当前实现与规范（CI 中的 Backup & Restore）

- 命名向量字段：`text`
  - 集合 Schema 固定为命名向量字段 `text` 且距离为 `Cosine`。
  - 创建集合示例：`{"vectors": {"text": {"size": <dim>, "distance": "Cosine"}}}`。
- 恢复目标集合命名：`<source>__restored`
  - 保留源集合（不删除），避免对现网集合造成影响。
- 数据恢复路径：直接对 Qdrant 写入（绕过后端 `/embedding/upsert`）
  - 先调用 `/embedding/embed` 生成 embeddings；
  - 再调用 Qdrant `PUT /collections/<coll>/points?wait=true` 批量 upsert：
    - 点结构：`{"points":[{"id":..., "vectors": {"text": [...]}, "payload": {...}}]}`。
  - 仅恢复 `payload.text` 为字符串的样本；如条目缺失 `id`，使用 `OFFSET+i` 生成确定性 id。
- 校验策略：
  - 使用 `POST /collections/<coll>/points/count` 设置 `exact=true` 做精确计数；
  - 增加重试（最多 5 次）缓解可见性延迟；
  - 额外使用 `scroll` 抽取前 10 条点位做直观确认；
  - CI 中为“软告警”，不阻断主干（计数不一致时发出 warning）。

> 注：README 中的 “Backup Signals（最近一次）” 支持自动刷新。开关由仓库变量 `UPDATE_README_SIGNALS` 控制，仅在 `main` 分支、且该变量为 `true` 时，`/.github/workflows/backup-restore.yml` 会在运行结束后自动更新 `README.md` 的占位块，并推送 commit（携带 `[skip ci]`）。

### 排查与诊断建议（出现计数不一致时）
- 打印每批次对齐情况：`fs_len`（过滤后样本数）、`vec_len`（embeddings 数量）与 sample point id；
- 检查 upsert 返回体是否 `status=="ok"`；
- 在恢复后执行一次 `scroll`，确认是否能取到前 10 条点位；
- 若需要不同的命名向量字段，请同时调整集合 Schema 与 upsert 的 `vectors.<name>` 字段以保持一致；
- 如仍存在延迟，考虑增加 `wait=true` 或在 `count` 前增加等待/重试。

## 恢复演练步骤
前提：有一份可用备份（zip/jsonl 等）；确保目标 Qdrant 可访问。

1) 创建隔离环境（建议）
- 新建空白集合或在测试命名空间进行恢复，避免污染现网。

2) 导入/恢复数据
- 若备份为 Qdrant 导出：
  - 使用 Qdrant 官方导入 API 或 `qdrant-client` 脚本导入
- 若备份为自定义 JSONL（向量+payload）：
  - 使用项目中的导入脚本（后续可补充）或临时 Python 脚本导入

3) 校验与对比
- 维度：
  - 集合统计：点位数量、分片状态、索引状态
  - 抽样查询：TopK 检索一致性
  - 业务评测：执行 `queries/rag_eval_50.jsonl` 的小样本评测
- 方法：
  - 通过 API `/collections`、`/embedding`、`/ask` 路由做 sanity check
  - 比对评测摘要 `artifacts/metrics/rag_eval.json` 的关键指标

4) 废弃演练环境
- 完成验证后清理临时集合或隔离命名空间

---

## 校验指引（Checklist）
- 集合存在且可检索
- 点位数量与索引状态正常（`indexed=True`）
- 抽样 TopK 结果稳定（与备份前差异在容忍阈内）
- RAG 评测通过最低门槛（如 hit_ratio≥0.60、avg_top1≥0.35）

---

## CI/文档挂钩（建议）
- 在 CI 增加“备份健康检查”步骤（可选）：
  - 对目标集合执行统计查询并输出到 `artifacts/metrics/backup_health.json`
- 在 `Progress Report` 的看板中追加备份状态快照（后续可通过脚本读取上述 JSON 注入）

---

## 常见问题
- 恢复耗时较长：检查硬件/容器 I/O，缩小批次或并发导入
- 向量维度不匹配：确认模型与集合 schema 保持一致
- 评测波动：适当扩大抽样、使用滑动平均

---

## 后续计划
- 增加恢复自动化脚本（从最新备份一键导入）
- 将恢复演练纳入季度例行检查并生成工件（日志、校验报告）

---

## 本次演练记录（2025-09-12 09:18 +08:00）

说明：本次为小样本演练，先行验证流程与工具可靠性，避免长命令“卡住”。

1) 备份（小样本）
- 产物：`artifacts/metrics/qdrant_demo_768_dump.json`（约 3.4K）
- 方法：`scripts/ci/backup_qdrant_collection.sh`，设置了 curl 超时与 MAX_BATCHES 保护（参见脚本注释）

2) 恢复至临时集合（隔离验证）
- 先显式创建集合（避免依赖后端自动建表）：
```
curl -sS --max-time 5 -X PUT \
  -H 'Content-Type: application/json' \
  -d '{"vectors":{"size":768,"distance":"Cosine"}}' \
  http://127.0.0.1:6333/collections/demo_768_tmp
```
- 执行恢复（逐条 embed + /embedding/upsert）：
```
export API_BASE=http://127.0.0.1:8000
export RAG_COLLECTION=demo_768_tmp
export SRC_DUMP=artifacts/metrics/qdrant_demo_768_dump.json
export BATCH_SIZE=32

bash scripts/ci/restore_qdrant_collection.sh
```
- 关键输出（摘要）：
```
[RESTORE] count=25 target=demo_768_tmp batch=32 src=artifacts/metrics/qdrant_demo_768_dump.json
[RESTORE] 本批 22 条，累计 22
[RESTORE] 完成，共恢复 22 条到 demo_768_tmp
```

3) 校验
- 集合元信息：`points_count=22`（状态 green）
- 精确计数：`{"result":{"count":22},"status":"ok"}`

4) 结论
- 流程打通：备份→恢复→计数验证全链路可用。
- 样本量：本次备份为小样本（约 3.4K 文件，恢复 22 条），可在需要时进行全量备份/恢复复测。

5) RTO/RPO（本次演练粗估）
- RTO：小样本恢复在数秒内完成；全量取决于集合规模与嵌入速度，建议批大小 32~128，必要时并行。
- RPO：由备份频率决定，建议每小时 1 次（可按业务要求调整）。

---

## 告警演练结论与复现指引（本地）

1) 关键指标摘录（来源：`http://127.0.0.1:8000/metrics`；见 `artifacts/metrics/metrics_probe_summary.md`）
- /api/v1/ask 200 次数：存在
- /api/v1/tools/invoke：200 和 502 均存在
- tools_requests_total、tools_errors_total：存在且随调用增长
- llm_generate_duration_seconds_count：存在
- tools_rate_limited_total、tools_circuit_open_total：本次未明显增量（顺序点击不足以触发限流；熔断需更稳定的失败源与窗口设定）

2) 复现建议
- 超时：在前端 `Tools` 页设置 `timeout_ms=50`；请求 `https://httpbin.org/delay/3`；预期 502（ConnectTimeout）。
- 熔断：使用固定失败目标 `https://invalid.invalid/`，设置 `retry_max=0, circuit_threshold=1, circuit_cooldown_ms=5000`，快速连点 ≥2 次；5s 后再点一次验证恢复；如仍无指标增量，建议在后端增加更直接的熔断打开计数指标。
- 限流：设置 `rate_limit_per_sec=2`，以高频快速连点（或小脚本 10 并发）模拟突发；随后查看 `tools_rate_limited_total` 是否增量。

3) CI 冒烟阈值
- 已在 `/.github/workflows/metrics-e2e.yml` 增加“Assert basic metrics thresholds (smoke gate)”步骤，防止关键指标缺失：
  - `/api/v1/ask` 的 200 计数
  - `tools_requests_total` 存在
  - `llm_generate_duration_seconds_count` 存在

---

## GitHub Actions Run #8 结果与工件

- 运行链接：https://github.com/Neal-yes/AI_Support_System/actions/runs/17721278528
- 工件下载：
  - https://github.com/Neal-yes/AI_Support_System/actions/runs/17721278528/artifacts/4008842495
- Job Summary（关键指标）：
  - collection: `default_collection`
  - seed_total: `5`
  - backup_total: `5`
  - restored_total: `5`
  - backup_duration_seconds: `0`
  - restore_duration_seconds (RTO): `1`
  - src: `demo.jsonl`
- 结论：备份与恢复一致性通过（backup_total=restored_total），RTO≈1s；流程稳定，工件上传成功。

### 工件校验（本地验证）

- 校验时间：2025-09-15 11:52 (+08:00)
- 本地路径：`download_artifacts/17721278528/`
- 校验结果：
  - `embedding_upsert.json`
    - total=5，src=demo.jsonl，collection=default_collection（断言通过）
  - `qdrant_default_collection_dump.json`
    - 文件结构为列表（list），长度=5（断言通过）
    - 抽样条目字段：`{"id": <uuid>, "payload": {"tag": "faq", "text": "...", "question": "...", "answer": null}}`

## GitHub Actions Run #9 结果与工件

- 运行链接：https://github.com/Neal-yes/AI_Support_System/actions/runs/17724192239
- 工件下载：
  - https://github.com/Neal-yes/AI_Support_System/actions/runs/17724192239/artifacts/4009654929
- Job Summary（关键指标）：
  - collection: `default_collection`
  - seed_total: `5`
  - backup_total: `5`
  - restored_total: `5`
  - backup_duration_seconds: `1`
  - restore_duration_seconds (RTO): `0`
  - src: `demo.jsonl`
- 校验摘要（已集成到 Job Summary 的 Artifact Validation）：
  - `embedding_upsert.json`: total=5, src=demo.jsonl, collection=default_collection
  - `qdrant_default_collection_dump.json`: type=list, len=5；sample keys: ['id', 'payload']
- 结论：新增“Validate artifacts”步骤验证通过；备份与恢复一致性通过，RTO≈0s；工件上传成功。

---

## Release Key Signals 的来源与兜底逻辑

Release 页面中的 `Key Signals` 段由工作流 `/.github/workflows/release-backup.yml` 的“Generate release notes”步骤生成。其数据来源与兜底顺序如下：

1) 主来源：`$out_dir/ci_summary.txt`
- 优先从 CI 汇总文本中提取：
  - `- success_rate:`（/api/v1/ask 的成功率）
  - `- endpoint: /api/v1/rag/preflight` 块中的 `success_rate:`
  - `- endpoint: /embedding/upsert` 块中的 `success_rate:`
  - `LLM generate p95` 与 `RAG retrieval p95`

2) 备选来源：`$out_dir/metrics_e2e_summary.txt`
- 当主来源缺失时，从 Metrics E2E 的 summary 文本提取相同字段。

3) Prom 兜底：`$out_dir/api_metrics.prom`
- 当文本类来源不足以给出数值时，基于 Prometheus 导出的快照 `api_metrics.prom` 计算：
  - `/api/v1/ask`、`/api/v1/rag/preflight`、`/embedding/upsert` 成功率：按 `http_requests_total{path="..."}` 和 `http_requests_total{path="...",status="200"}` 聚合计算。
  - `llm_generate_duration_seconds` 与 `rag_retrieval_duration_seconds` 的 p95：按 `_bucket{le="..."}` 累积求 95 分位。

4) 工件获取与最终兜底
- 若 `$out_dir/metrics_e2e_summary.txt` 或 `$out_dir/api_metrics.prom` 缺失：
  - 主动拉取最近一次成功的 Metrics E2E 工件（优先同分支 `GITHUB_REF_NAME`；否则退化为全局最新成功），并解压复制 `metrics_e2e_summary.txt` 与 `api_metrics.prom` 到 `$out_dir/`。
- 若仍缺 `api_metrics.prom`：
  - 在 `$out_dir` 树内深度查找并复制任何命中的 `api_metrics.prom`；
  - 如果没有，则尝试使用 `metrics_probe.prom` 复制为 `$out_dir/api_metrics.prom`。

5) 可观测性
- 工作流会打印 `-- OUT_DIR LISTING --` 显示 `$out_dir` 顶层文件，便于排查。
- 在 `RELEASE_NOTES.md` 中嵌入 `<!-- KS_DEBUG ... has_prom=... -->` 注释，同时在日志 `::group::KS DEBUG` 段输出同样信息；当 `$out_dir/api_metrics.prom` 文件存在且非空时，`has_prom` 为 1。

上述机制确保 `Key Signals` 在多数情况下稳定产出；即便 E2E 文本汇总缺失，也可利用 Prom 快照计算出核心指标。
