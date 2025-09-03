import { test, expect } from '@playwright/test'

// This test relies on webServer configured in playwright.config.ts
// It verifies the version badge Vx.y.z is visible in the top bar.

test('shows version badge in topbar', async ({ page }) => {
  await page.goto('/')
  // Wait for app to render
  const ver = page.locator('.ver')
  await expect(ver).toBeVisible()
  const txt = (await ver.textContent())?.trim() || ''
  // Expect starts with 'V' and follows semver-like pattern (major.minor.patch)
  expect(txt).toMatch(/^V\d+\.\d+\.\d+$/)
})
