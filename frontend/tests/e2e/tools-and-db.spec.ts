import { test, expect } from '@playwright/test'

// Minimal smoke tests for Tools and DB pages

test.describe('Tools & DB pages', () => {
  test('Tools page renders core form and buttons', async ({ page }) => {
    await page.goto('/tools')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { level: 2, name: /Invoke Tool/i })).toBeVisible()
    // Core fields
    await expect(page.getByLabel(/Tenant/i)).toBeVisible()
    await expect(page.getByLabel(/Type/i)).toBeVisible()
    await expect(page.getByLabel(/Name/i)).toBeVisible()
    await expect(page.getByLabel(/Params/i)).toBeVisible()
    await expect(page.getByRole('button', { name: /Invoke/i })).toBeVisible()
  })

  test('DB page renders core form and result area', async ({ page }) => {
    await page.goto('/db')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { level: 2, name: /DB Template Query/i })).toBeVisible()
    await expect(page.getByLabel(/Template ID/i)).toBeVisible()
    await expect(page.getByLabel(/Template Version/i)).toBeVisible()
    await expect(page.getByLabel(/Params \(JSON\)/i)).toBeVisible()
    await expect(page.getByRole('button', { name: /Execute/i })).toBeVisible()
    // Result pre element exists
    await expect(page.locator('pre')).toBeVisible()
  })
})
