import { test, expect } from '@playwright/test'

// This test verifies that the app header shows a semantic version chip
// and that it follows semver-like format (x.y.z[-prerelease]).
// It also checks the title attribute contains the same version string.

test.describe('App version chip', () => {
  test('should be visible and formatted like semver', async ({ page, baseURL }) => {
    // Navigate to home (baseURL is configured in playwright.config.ts)
    await page.goto(baseURL || '/')

    const chip = page.locator('.topbar .ver')
    await expect(chip).toBeVisible({ timeout: 10000 })

    const text = (await chip.textContent())?.trim() || ''
    // Basic semver pattern: 1.2.3 or 1.2.3-beta.1
    const semverRe = /^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$/
    expect.soft(text).toMatch(semverRe)

    const title = await chip.getAttribute('title')
    expect.soft(title || '').toContain(text)
  })
})
