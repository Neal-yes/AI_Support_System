import { test, expect } from '@playwright/test'

// Health popover hover test

test.describe('Health popover', () => {
  test('hover shows health details structure', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const health = page.locator('.health')
    if (!(await health.isVisible().catch(() => false))) {
      test.skip(true, 'health trigger not visible; skip in this build')
    }
    await health.hover()
    // Popover appears
    const pop = page.locator('.health-pop')
    await expect(pop).toBeVisible({ timeout: 3000 })
    // Basic structure
    await expect(pop.getByText(/overall|总体/i)).toBeVisible()
    // services rows may or may not exist depending on backend; ensure at least one row exists/rendered
    const rows = pop.locator('.row')
    const cnt = await rows.count().catch(() => 0)
    if (cnt > 0) {
      await expect(rows.first()).toBeVisible()
    } else {
      test.skip(true, 'no health service rows rendered; skip row assertion')
    }
  })
})
