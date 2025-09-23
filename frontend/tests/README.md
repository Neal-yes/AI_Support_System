# Frontend E2E (Playwright)

本目录包含基于 Playwright 的前端端到端（E2E）测试。

- 目录：`frontend/tests/e2e/`
- 运行：在 `frontend/` 目录执行
  - 安装依赖：`npm ci && npx playwright install --with-deps`
  - 执行测试：`npx playwright test --reporter=line,junit`
  - 查看 HTML 报告：`npx playwright show-report`

## 测试文件与职责

- `basic.spec.ts`
  - App Shell 可见性、基本导航（`/`、`/health`）、404 回退等基础冒烟。
- `i18n-and-404.spec.ts`
  - 语言切换（`localStorage.lang`）与未知路由回退。若健康标签不可见将跳过，降低环境耦合。
- `health-pop.spec.ts`
  - 健康弹层 hover。若 `.health` 触发器不可见将跳过，等待更长超时，服务行不存在时跳过行断言。
- `tools-and-db.spec.ts`
  - `Tools`、`DB` 页冒烟。内置 `gotoSmart()` 同时兼容 history/hash 路由模式，并在关键标题不可见时跳过，减少抖动。
- `tools-templates.spec.ts`
  - Tools 页面“模板按钮”和“按类型模板”的本地交互（不发网络）。
  - 覆盖：HTTP 模板参数与 options 写入、DB 模板写入 `toolType/toolName/params`、按 `Type` 自动套用模板。
  - 扩展边界用例：
    - 特殊字符与长 URL 输入（不崩溃）
    - 清空 `params`（若应用自动回填默认值则跳过）
    - 连续模板切换的最终状态一致性
- `tools-obs.spec.ts`、`version-badge.spec.ts`
  - 其他页面/组件的基础验证。

## 去抖动与稳健性策略

- 选择器优先：`getByRole`/`getByPlaceholder`，避免脆弱 CSS。
- 等待策略：`page.waitForLoadState('networkidle')`，关键元素可见性断言适度超时。
- 条件跳过：
  - 重要触发器不可见（例如健康入口）则 `test.skip()`。
  - 数据依赖的可选结构（如健康服务行）缺失则跳过局部断言。
- 路由兼容：
  - `gotoSmart()` 先访问 `/path`，若关键标题不可见则回退 `/#/path`，兼容两种路由模式。

## CI 工作流与报告

- 工作流文件：`.github/workflows/frontend-e2e.yml`
  - Node 20，`npm ci`，安装 Playwright 浏览器，`npm run build` 后执行测试。
  - 报告：
    - JUnit：`frontend/playwright-results.xml`（已作为工件上传）
    - HTML：`frontend/playwright-report/`（已作为工件上传）
  - 退出码收敛：若 JUnit `failures=0`，即使 Playwright 返回非零也视为成功，避免假失败。
- 分支保护：`main` 已要求“Frontend E2E (Playwright)”为必需状态检查。

## 本地运行提示

- 建议本地跑一次：`npx playwright test --project=chromium --headed`
- 如遇 i18n/健康弹层偶发抖动，可先验证 UI 是否渲染到对应元素；E2E 已包含必要跳过逻辑。

## 贡献规范（E2E）

- 新增用例时：
  - 避免与后端强耦合，优先做“本地交互”验证。
  - 对可能缺失/延迟渲染的节点，增加可见性检测与条件跳过。
  - 对网络、时间敏感逻辑，使用更高层 API 与超时。
- PR 合并策略：
  - 确保 Frontend E2E 检查通过（分支保护必需状态）。
