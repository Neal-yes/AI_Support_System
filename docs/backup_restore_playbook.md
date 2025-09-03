# 备份 / 恢复演练手册（Playbook）

更新时间：2025-09-03 09:26 (+08:00)

目的：提供可落地、可复用的 Qdrant 向量库与相关工件的备份/恢复方案与演练步骤，明确 RTO/RPO 目标与校验指引。

---

## 术语
- RTO（恢复时间目标）：≤ 15 分钟（开发/测试环境）。
- RPO（恢复点目标）：≤ 1 小时（定时备份频率可调）。

---

## 备份方案
- 对象：Qdrant 集合（含向量与 payload）、关键配置与评测工件。
- 工具/脚本：`scripts/backup_qdrant_collection.sh`
- 建议频率：每小时一次；保留最近 N（默认 24）份。

### 手动备份
```bash
# 必要环境：QDRANT_URL（默认 http://localhost:6333）、COLLECTION
export COLLECTION=metrics_demo_1d
bash scripts/backup_qdrant_collection.sh
```

### 产物位置
- 默认：`download/` 或 `download_artifacts/<timestamp>/`
- 归档：建议将最近一次备份同步到对象存储（可选）

---

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
