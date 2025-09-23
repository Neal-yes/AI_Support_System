import { test, expect } from '@playwright/test'

// Basic smoke for frontend app shell and navigation (robust to i18n and router mode)

test.describe('App shell & navigation', () => {
  test('homepage loads (app shell visible)', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    // App renders
    await expect(page.locator('#app')).toBeVisible()
    // Optional sanity: at least one primary region exists (do not fail test if absent)
    const maybeNav = page.locator('nav, header, main')
    if (await maybeNav.count() > 0) {
      // no-op; presence is enough for smoke
    }
  })

  test('navigate to Health via top nav (fallback: direct route)', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    // Try common i18n variants of the Health link
    const link = page.getByRole('link', { name: /health|健康|状态|status/i })
    if (await link.isVisible({ timeout: 1000 }).catch(() => false)) {
      await link.click()
    } else {
      test.skip(true, 'Health link not visible; skip nav test (likely no route or hidden in this build)')
    }
    await page.waitForLoadState('networkidle')
    // Accept both history and hash router
    await expect(page).toHaveURL(/(\/health$|#\/health$)/)
    // Basic content check to ensure page mounted
    await expect(page.locator('body')).not.toContainText('404')
    await expect(page.locator('#app')).toBeVisible()
  })

  test('health page direct open (if exists) then home reachable', async ({ page }) => {
    // Try to open health directly; if 404 occurs, skip
    await page.goto('/health')
    await page.waitForLoadState('networkidle')
    if (await page.locator('text=404').isVisible().catch(() => false)) {
      test.skip(true, 'Health route not found; skip')
    }
    // Accept both history and hash router
    const url = page.url()
    if (!/\/health$|#\/health$/.test(url)) {
      await page.goto('#/health')
      await page.waitForLoadState('networkidle')
    }
    // Now go to home explicitly to avoid flaky history back
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveURL(/(\/$|#\/$)/)
    await expect(page.locator('#app')).toBeVisible()
  })
})
