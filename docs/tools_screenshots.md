# /tools 调试面板截图与动图采集指南

为便于用户快速理解“观测链接 + 模板预览/测试 + 导入导出”等功能，建议采集以下截图/动图并按如下文件名保存到 `docs/assets/` 目录（建议新建该目录）。

请按列表逐项采集，采集完成后 README 中的占位图片即可正常展示。

## 建议采集清单

- 01 面板总览（含输入与表格）
  - 文件：`docs/assets/tools-overview.png`
  - 说明：展示 tenant/type/name、params/options、策略 Diff 表、Obs 列按钮。

- 02 观测链接表单（含环境默认值）
  - 文件：`docs/assets/tools-obs-form.png`
  - 说明：展示 Prom/Logs 基地址、模板输入、环境默认值预填（如有）。

- 03 模板预览与测试打开
  - 文件：`docs/assets/tools-obs-preview-test.png`
  - 说明：输入“测试键名”，下方 PromQL/日志查询实时预览；展示“测试打开指标/日志”按钮。

- 04 导入/导出配置
  - 文件：`docs/assets/tools-obs-import-export.png`
  - 说明：展示“导出配置/导入配置”按钮与选择文件弹窗（如可截）。

- 05 URL 校验与提示
  - 文件：`docs/assets/tools-obs-validation.png`
  - 说明：基地址非法时的红色提示、测试按钮禁用与 title 提示。

- 06 表格行级 Obs 跳转
  - 文件：`docs/assets/tools-obs-row-actions.png`
  - 说明：表格每行的“指标/日志”跳转按钮。

- 07 动图（可选）
  - 文件：`docs/assets/tools-obs-demo.gif`
  - 说明：从填写观测配置、预览模板、测试打开，到在表格点击行级 Obs 的完整演示。
  - 备注：若环境未安装 ffmpeg 或不便生成 GIF，可直接提交静态帧序列目录 `docs/assets/gif_frames/`（frame01.png ~ frame06.png）作为替代；后续有需要时再行合成。

## 采集建议

- 分辨率：建议 1440x900 或更高；动图控制在 5-15 秒内，突出关键步骤。
- 隐私：如包含内网地址或敏感租户名，请打码处理。
- 命名：严格遵守上述文件名，避免修改 README 中的图片路径。

## 启用态（文字说明）

无需额外截图，可用以下要点确认观测配置处于“启用态”：

- 必填项已合法：`Prom 基地址` 与 `日志基地址` 为可访问的 HTTP(S) URL，`查询模板` 非空；`测试键名` 已填写。
- 交互启用：按钮“测试打开指标/日志”处于可点击状态（非禁用、无红色提示）。
- 预览生效：`PromQL 预览` 与 `日志查询预览` 自动将 `$tenant/$type/$name/$key` 替换为页面上当前值，如 `default/http_get.simple/timeout_ms`。
- 导出导入：
  - 点击“导出配置”会下载 JSON；
  - 通过 `docs/assets/toolsObsConf.json` 导入后，四个字段会被正确回填并立即影响预览与按钮状态。
- 链接可达性：
  - 指标通常指向本地 Prometheus（如 `http://localhost:9090/query`）应可打开；
  - 日志示例域 `https://logs.example.com/search` 可能不可达，这不影响功能验证（仅用于校验 URL 生成与跳转逻辑）。

- 校验实现：
  - 前端统一使用 `frontend/src/utils/obs.ts` 中的 `isValidHttpUrl()` 执行 `http/https` 基地址校验；
  - 表单红色提示与“测试打开指标/日志”按钮禁用状态与该校验逻辑保持一致。

## FAQ

- 图片未显示？检查文件是否已保存至 `docs/assets/`，并确认 README 中引用路径正确。
- 动图过大？可通过压缩工具降低帧率或分辨率。

## 导入/导出：边界用例与一致性校验

- **缺字段**：导入 JSON 缺失某个字段时（如 `promQueryTpl`），页面保留现有值，不清空该字段。
- **空字符串**：导入 `promQueryTpl`/`logsQueryTpl` 为 `""` 时不覆盖现有模板，避免清空。
- **多余字段**：导入包含未知字段（如 `extra`）将被忽略，不影响现有表单。
- **模板特殊字符/超长字符串**：导出后重新导入应保持完全一致；E2E 使用 `toHaveValue` 等待异步回填完成，确保一致性。
- **导出文件大小随模板增长增加**：当模板显著变长，导出 `toolsObsConf.json` 的体积应明显增大（用于验证内容包含）。
- **文件过大限制**：导入文件大小超过 1MB 时给出友好提示，防止浏览器卡顿（`frontend/src/views/Tools.vue` 中实现）。
- **JSON 解析错误**：导入非 JSON 或损坏 JSON 时会弹窗提示（保留原值）。

字段清单（导出文件固定名：`toolsObsConf.json`）：

- `promBase`: string
- `promQueryTpl`: string
- `logsBase`: string
- `logsQueryTpl`: string
- `version`: number（当前为 1）
- `exportedAt`: string（ISO 时间）

## 运行与报告查看指引（前端）

- **仅运行单测（Vitest）**：
  ```bash
  npm --prefix frontend run test --silent
  # 或仅某文件
  npm --prefix frontend run test --silent -- src/utils/obs.test.ts
  ```
  - 已配置 `frontend/vitest.config.ts`：仅收集 `src/**/*.test.ts`，排除 `tests/e2e/**`；并将 `server.host` 设为 `127.0.0.1` 以规避部分环境下 `localhost` 解析异常。

- **运行 E2E（Playwright）**：
  ```bash
  npm --prefix frontend run test:e2e --silent
  ```
  - 查看报告：直接打开 `frontend/playwright-report/index.html`。

## 常见排错

- **Vitest 收集到 E2E 文件**：
  - 现已通过 `vitest.config.ts` 排除 `tests/e2e/**`。若自定义路径，请确认 include/exclude 设置正确。

- **getaddrinfo ENOTFOUND localhost**：
  - 某些环境 `localhost` 解析异常；已在 `vitest.config.ts` 中设置 `server.host = '127.0.0.1'`，如仍出现请检查系统 hosts 配置。

- **Playwright 报告路径**：
  - `npx playwright show-report` 默认在当前目录查找 `playwright-report/`；本项目报告位于 `frontend/playwright-report/`，建议直接打开 `index.html`。

- **导入失败提示**：
  - 超过大小限制或 JSON 解析错误时将弹窗提示并保持原值，避免误覆盖；如需调试，可在浏览器控制台查看异常信息。
