import { test, expect } from '@playwright/test'

// i18n and unknown-route fallback smoke tests

test.describe('i18n & fallback', () => {
  test('language switch via localStorage persists and reflects in health label', async ({ page }) => {
    // Force English first
    await page.addInitScript(() => localStorage.setItem('lang', 'en'))
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const label = page.locator('.health .label')
    await expect(label).toBeVisible()
    const enText = (await label.textContent())?.trim().toLowerCase()
    // One of English variants
    expect(enText && ['checking', 'ready', 'degraded', 'error'].includes(enText)).toBeTruthy()

    // Now switch to zh and reload
    await page.addInitScript(() => localStorage.setItem('lang', 'zh'))
    await page.reload()
    await page.waitForLoadState('networkidle')
    const zhText = (await label.textContent())?.trim()
    // One of Chinese variants
    const zhSet = ['检查中', '就绪', '降级', '错误']
    expect(zhText && zhSet.some(s => zhText.includes(s))).toBeTruthy()
  })

  test('unknown route does not crash app (fallback to app shell)', async ({ page }) => {
    await page.goto('/__this_route_should_not_exist__')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('#app')).toBeVisible()
    // Basic header still visible
    await expect(page.getByRole('heading', { name: /AI Support System/i })).toBeVisible()
  })
})
