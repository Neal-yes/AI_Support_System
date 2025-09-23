import { test, expect } from '@playwright/test'

// Basic smoke for frontend app shell and navigation

test.describe('App shell & navigation', () => {
  test('homepage loads and shows top navigation', async ({ page }) => {
    await page.goto('/')
    // App renders
    await expect(page.locator('#app')).toBeVisible()
    // Top nav exists
    await expect(page.locator('nav')).toBeVisible()
  })

  test('navigate to Health via top nav', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /health/i }).click()
    await expect(page).toHaveURL(/\/health$/)
    // Basic content check to ensure page mounted
    await expect(page.locator('body')).not.toContainText('404')
  })

  test('back to home works', async ({ page }) => {
    await page.goto('/health')
    await page.goBack()
    await expect(page).toHaveURL(/\/$/)
  })
})
