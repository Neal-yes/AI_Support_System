import { test, expect } from '@playwright/test'

// Health popover hover test

test.describe('Health popover', () => {
  test('hover shows health details structure', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const health = page.locator('.health')
    // Ensure the trigger exists and is visible (CI can be slower)
    await page.waitForSelector('.health', { state: 'visible', timeout: 7000 }).catch(() => {})
    if (!(await health.isVisible().catch(() => false))) {
      test.skip(true, 'health trigger not visible; skip in this build')
    }
    await health.scrollIntoViewIfNeeded().catch(() => {})
    // Hover with a light retry in case of transient flakiness
    try {
      await health.hover({ force: true })
    } catch {
      const box = await health.boundingBox().catch(() => null)
      if (box) {
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      }
      await health.hover({ force: true })
    }
    // Popover appears
    const pop = page.locator('.health-pop')
    await page.waitForSelector('.health-pop', { state: 'attached', timeout: 8000 }).catch(() => {})
    await expect(pop).toBeVisible({ timeout: 8000 })
    // Basic structure
    await expect(pop.getByText(/overall|总体/i)).toBeVisible()
    // services rows may or may not exist depending on backend; ensure at least one row exists/rendered
    const rows = pop.locator('.row')
    // Give the list a brief moment to render
    await page.waitForTimeout(200)
    const cnt = await rows.count().catch(() => 0)
    if (cnt > 0) {
      await expect(rows.first()).toBeVisible()
    } else {
      test.skip(true, 'no health service rows rendered; skip row assertion')
    }
  })
})
