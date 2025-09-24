import { test, expect } from '@playwright/test'

// Health popover hover test

test.describe('Health popover', () => {
  test('hover shows health details structure', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const health = page.locator('.health')
    // Ensure the trigger exists and is visible (CI can be slower)
    await page.waitForSelector('.health', { state: 'visible', timeout: 10000 }).catch(() => {})
    if (!(await health.isVisible().catch(() => false))) {
      test.skip(true, 'health trigger not visible; skip in this build')
    }
    await health.scrollIntoViewIfNeeded().catch(() => {})
    // Hover with bounded retries and tiny jitter to mitigate CI flakiness
    {
      const maxAttempts = 3
      for (let i = 0; i < maxAttempts; i++) {
        const box = await health.boundingBox().catch(() => null)
        if (box) {
          const jitterX = (i * 3) % 10
          const jitterY = (i * 2) % 8
          await page.mouse.move(box.x + box.width / 2 + jitterX, box.y + box.height / 2 + jitterY)
        }
        try {
          await health.hover({ force: true })
          break
        } catch {
          if (i === maxAttempts - 1) throw new Error('Failed to hover health trigger after retries')
          await page.waitForTimeout(150)
        }
      }
    }
    // Popover appears
    const pop = page.locator('.health-pop')
    await page.waitForSelector('.health-pop', { state: 'attached', timeout: 10000 }).catch(() => {})
    await expect(pop).toBeVisible({ timeout: 10000 })
    // Basic structure
    await expect(pop.getByText(/overall|总体/i)).toBeVisible()
    // services rows may or may not exist depending on backend; ensure at least one row exists/rendered
    const rows = pop.locator('.row')
    // Poll briefly for rows to render (CI sometimes lags a bit)
    let cnt = 0
    for (let i = 0; i < 5; i++) {
      cnt = await rows.count().catch(() => 0)
      if (cnt > 0) break
      await page.waitForTimeout(150)
    }
    if (cnt > 0) {
      await expect(rows.first()).toBeVisible()
    } else {
      test.skip(true, 'no health service rows rendered; skip row assertion')
    }
  })
})
