# Changelog

## [Unreleased]

### Added
- 支持在 `POST /embedding/upsert` 中使用字符串 UUID 作为 `ids`（`UpsertRequest.ids: Optional[List[Union[int, str]]]`）。
- 新增 E2E 测试 `tests/test_embedding_uuid_upsert.py`：验证 UUID upsert → search → preflight 全链路。
- 新增批处理脚本 `scripts/batch_reupsert.py`：读取 JSONL 分批 re-upsert，自动补齐 `payload.text`，支持 UUID。
- 在 `README.md` 补充“UUID 覆盖 upsert 与 422 排错”示例与复检命令。
- 在 `src/app/routers/embedding.py` 的 `upsert()` 增加 docstring，说明 ids 类型与 422 排错步骤。

### Changed
- 无。

### Fixed
- 无。
