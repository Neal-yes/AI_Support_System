import { test, expect } from '@playwright/test'

// Health popover hover test

test.describe('Health popover', () => {
  test('hover shows health details structure', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const health = page.locator('.health')
    await expect(health).toBeVisible()
    await health.hover()
    // Popover appears
    const pop = page.locator('.health-pop')
    await expect(pop).toBeVisible()
    // Basic structure
    await expect(pop.getByText(/overall|总体/i)).toBeVisible()
    // services rows may or may not exist depending on backend; ensure at least one row exists/rendered
    const firstRow = pop.locator('.row').first()
    await expect(firstRow).toBeVisible()
  })
})
