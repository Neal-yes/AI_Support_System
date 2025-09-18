# 按周推进计划（Progress Plan）

更新时间：2025-09-03 09:06 (+08:00)

目标：补齐 M1 必需项、推进 M1.5 关键增强，并搭建持续可视化的“进度雷达图/看板工件”。

---

## W1（本周）：M1 必需项收口与自动化可视化落地
- 【CI/可视化】新增进度工作流与工件
  - 产出：`.github/workflows/progress.yml`、`scripts/ci/gen_progress_report.py`、`artifacts/progress/*`
  - 验收：PR 合并后自动产出雷达图、kanban.md、summary.json 并上传。
- 【前端】版本号一致性（Vx.y.z 固定展示）
  - 产出：`frontend` 全局头部展示版本；从 package.json / env 注入；补充单测/E2E 快照。
  - 验收：E2E 截图中可见版本号；CI 保证 JUnit 报告展示通过。
- 【RAG/模型】基线产出
  - 产出：RAG 命中率与 avg_top1 基线，记录到 `artifacts/metrics` 与 Grafana 面板。
  - 验收：CI Gate 保持运行，面板可查看最新一次基线。
- 【备份/恢复】文档初稿
  - 产出：`docs/backup_restore_playbook.md`（RTO/RPO、演练步骤、校验指引）。
  - 验收：评审通过；计划 W2 执行演练。

## W2：恢复演练与发布前评测（CD）
- 【备份/恢复】执行恢复演练
  - 产出：恢复日志、校验截图、`docs/backup_restore_runbook.md` 更新“实操记录”。
  - 验收：在隔离环境完成全量恢复，校验通过。
- 【CD】新增发布前评测工作流
  - 产出：`.github/workflows/cd_predeploy.yml`（部署前触发回归主集与 RAG gate，不达标阻断）。
  - 验收：合并到 main 后能在 release 分支/标签触发并上传报告。
- 【RAG/模型】P95 性能基线（缓存命中）
  - 产出：压测脚本与报告；Prometheus 指标（耗时直方图）。
  - 验收：Grafana 展示 P95≤2s（缓存命中路径）。

## W3：复合编排与 Singleflight、策略完善
- 【工具编排】串/并行与预算策略用例
  - 产出：编排 DSL/配置样例；单测覆盖。
  - 验收：CI 通过并生成示例执行轨迹工件。
- 【权限】ABAC 最小闭环
  - 产出：策略模型（资源/操作/属性），列级脱敏 PoC。
  - 验收：关键接口通过策略校验，新增审计字段（reason_code）。

## W4：多租户与体验增强（持续打磨）
- 【多租户】隔离模型与数据路径设计
  - 产出：租户上下文注入、Qdrant 集合/命名空间策略。
  - 验收：用例覆盖跨租户访问阻断。
- 【前端/体验】Chat 完整版雏形与无障碍
  - 产出：基础 Chat UI 与快捷键、ARIA 标签。
  - 验收：E2E 用例与无障碍扫描通过。

---

## 风险与应对
- 【模型拉取时长/网络不稳定】
  - 方案：CI 中 best-effort 预拉取、超时不阻断；本地使用缓存镜像。
- 【评测波动】
  - 方案：增加样本量与滑动平均；结果工件化做留存对比。
- 【CD 环节外部依赖】
  - 方案：先落地干跑（dry-run）与报告工件，再接入真实发布。

---

## 可交付产物一览（每周至少可见）
- 进度雷达图：`artifacts/progress/progress_radar.png`
- 进度看板：`artifacts/progress/kanban.md`
- 进度摘要：`artifacts/progress/summary.json`
- 评测与日志：`artifacts/metrics/*`、`download_artifacts/*`

如需，我可以同步维护每周复盘模板（问题清单、指标快照与下周计划）。
