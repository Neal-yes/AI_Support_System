import { test, expect } from '@playwright/test'

// Minimal smoke tests for Tools and DB pages

test.describe('Tools & DB pages', () => {
  test('Tools page renders core form and buttons', async ({ page }) => {
    await page.goto('/tools')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { level: 2, name: /Invoke Tool/i })).toBeVisible()
    // Core fields via placeholders (labels lack for/id association)
    await expect(page.getByPlaceholder('default')).toBeVisible()
    await expect(page.getByPlaceholder('http_get')).toBeVisible()
    await expect(page.getByPlaceholder('simple')).toBeVisible()
    await expect(page.getByPlaceholder('{"url":"https://example.com"}')).toBeVisible()
    await expect(page.getByRole('button', { name: /Invoke/i })).toBeVisible()
  })

  test('DB page renders core form and result area', async ({ page }) => {
    await page.goto('/db')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { level: 2, name: /DB Template Query/i })).toBeVisible()
    await expect(page.getByPlaceholder('echo_int')).toBeVisible()
    await expect(page.getByPlaceholder('(optional, e.g. v1)')).toBeVisible()
    await expect(page.getByPlaceholder('{"x": 123}')).toBeVisible()
    await expect(page.getByRole('button', { name: /Execute/i })).toBeVisible()
    // Result pre element exists
    await expect(page.locator('pre')).toBeVisible()
  })
})
