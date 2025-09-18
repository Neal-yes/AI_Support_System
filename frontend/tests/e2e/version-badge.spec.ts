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
  // Accept variants: 'Vx.y.z', 'version: x.y.z', or raw 'x.y.z'
  const ok = /^V\d+\.\d+\.\d+$/.test(txt)
    || /^version:\s*\d+\.\d+\.\d+$/i.test(txt)
    || /^\d+\.\d+\.\d+$/.test(txt)
  expect(ok, `unexpected version badge text: "${txt}"`).toBeTruthy()
})
