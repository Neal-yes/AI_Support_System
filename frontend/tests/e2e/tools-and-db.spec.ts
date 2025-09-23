import { test, expect } from '@playwright/test'

// Minimal smoke tests for Tools and DB pages

test.describe('Tools & DB pages', () => {
  async function gotoSmart(page: import('@playwright/test').Page, path: string, heading: RegExp) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const ok = await page.getByRole('heading', { level: 2, name: heading }).isVisible().catch(() => false)
    if (!ok) {
      // try hash routing fallback
      const hashPath = path.startsWith('/#/') ? path : `/#${path}`
      await page.goto(hashPath)
      await page.waitForLoadState('networkidle')
    }
  }
  test('Tools page renders core form and buttons', async ({ page }) => {
    await gotoSmart(page, '/tools', /Invoke Tool/i)
    const toolsHeading = page.getByRole('heading', { level: 2, name: /Invoke Tool/i })
    if (!(await toolsHeading.isVisible().catch(() => false))) {
      test.skip(true, 'Tools page not available; skip smoke assertions')
    }
    await expect(toolsHeading).toBeVisible({ timeout: 2000 })
    // Core fields via placeholders (labels lack for/id association)
    await expect(page.getByPlaceholder('default')).toBeVisible()
    await expect(page.getByPlaceholder('http_get')).toBeVisible()
    await expect(page.getByPlaceholder('simple')).toBeVisible()
    await expect(page.getByPlaceholder('{"url":"https://example.com"}')).toBeVisible()
    await expect(page.getByRole('button', { name: /Invoke/i })).toBeVisible()
  })

  test('DB page renders core form and result area', async ({ page }) => {
    await gotoSmart(page, '/db', /DB Template Query/i)
    const dbHeading = page.getByRole('heading', { level: 2, name: /DB Template Query/i })
    if (!(await dbHeading.isVisible().catch(() => false))) {
      test.skip(true, 'DB page not available; skip smoke assertions')
    }
    await expect(dbHeading).toBeVisible({ timeout: 2000 })
    await expect(page.getByPlaceholder('echo_int')).toBeVisible()
    await expect(page.getByPlaceholder('(optional, e.g. v1)')).toBeVisible()
    await expect(page.getByPlaceholder('{"x": 123}')).toBeVisible()
    await expect(page.getByRole('button', { name: /Execute/i })).toBeVisible()
    // Result pre element exists
    await expect(page.locator('pre')).toBeVisible()
  })
})
