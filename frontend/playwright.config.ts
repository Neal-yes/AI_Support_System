import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // 在 CI 环境下启用重试以提升稳定性
  retries: process.env.CI ? 2 : 0,
  // 禁止在 CI 中提交 .only 的测试
  forbidOnly: !!process.env.CI,
  // 明确产物与报告设置
  outputDir: 'test-results',
  reporter: [
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
    ['junit', { outputFile: 'playwright-results.xml' }],
  ],
  // 并发控制：在 CI 中限制 workers 数量，降低资源抖动导致的偶发失败
  workers: process.env.CI ? 2 : undefined,
  use: {
    baseURL: 'http://127.0.0.1:5177',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
  webServer: {
    command: 'npm run preview:5177',
    url: 'http://127.0.0.1:5177',
    reuseExistingServer: true,
    timeout: 240_000,
  },
})
