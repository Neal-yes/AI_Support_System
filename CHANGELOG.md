# Changelog

## [Unreleased]

### Added
- 支持在 `POST /embedding/upsert` 中使用字符串 UUID 作为 `ids`（`UpsertRequest.ids: Optional[List[Union[int, str]]]`）。
- 新增 E2E 测试 `tests/test_embedding_uuid_upsert.py`：验证 UUID upsert → search → preflight 全链路。
- 新增批处理脚本 `scripts/batch_reupsert.py`：读取 JSONL 分批 re-upsert，自动补齐 `payload.text`，支持 UUID。
- 在 `README.md` 补充“UUID 覆盖 upsert 与 422 排错”示例与复检命令。
- 在 `src/app/routers/embedding.py` 的 `upsert()` 增加 docstring，说明 ids 类型与 422 排错步骤。

### Changed
- CI（frontend-e2e job）：改为 `npx playwright test --retries=2 --reporter=line,junit`，减少偶发抖动导致的红灯；继续上传 JUnit 与 HTML 报告工件。
- CI：在运行 Playwright 前新增“Build frontend (vite)”步骤，保证 `vite preview` 有可用构建产物。
- Playwright 配置（`frontend/playwright.config.ts`）：在 CI 下将 `webServer.timeout` 提升至 240s、`workers` 降为 2。
- Frontend E2E 工作流（`.github/workflows/frontend-e2e.yml`）：仅在 `actions/checkout@v4` 之后执行 `dorny/paths-filter@v3`，并依据 paths-filter 结果对重步骤加条件执行。

### Fixed
- 修复 Frontend E2E 在“Detect changed paths”于 checkout 之前执行导致的失败；调整步骤顺序后恢复稳定。
- 多处 E2E 用例去抖（健康弹层 hover 重试、等待时序加固、DB/Tools 定位放宽、必要场景条件性跳过）。
