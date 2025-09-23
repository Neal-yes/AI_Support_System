import { test, expect } from '@playwright/test'

// Tools page: verify template buttons mutate form fields locally (no network)

test.describe('Tools templates (local interactions)', () => {
  test('HTTP templates mutate params/options as expected', async ({ page }) => {
    await page.goto('/tools')
    await page.waitForLoadState('networkidle')

    const typeInput = page.getByPlaceholder('http_get')
    const nameInput = page.getByPlaceholder('simple')
    const paramsArea = page.getByPlaceholder('{"url":"https://example.com"}')
    const optionsArea = page.getByPlaceholder('{"timeout_ms":2000, "allow_hosts":["example.com"], "deny_hosts":[]}')

    // GET 模板
    await page.getByRole('button', { name: 'GET 模板' }).click()
    await expect(paramsArea).toHaveValue(/https:\/\/example\.com/)

    // POST 模板
    await page.getByRole('button', { name: 'POST 模板' }).click()
    await expect(paramsArea).toHaveValue(/https:\/\/httpbin\.org\/post/)

    // POST(Text) 模板 应写入 content_type=text/plain 到 options
    await page.getByRole('button', { name: 'POST(Text)' }).click()
    await expect(typeInput).toHaveValue('http_post')
    await expect(nameInput).toHaveValue('simple')
    await expect(optionsArea).toHaveValue(/text\/plain/)

    // POST(Form) 模板 应写入 content_type=application/x-www-form-urlencoded 到 options
    await page.getByRole('button', { name: 'POST(Form)' }).click()
    await expect(typeInput).toHaveValue('http_post')
    await expect(nameInput).toHaveValue('simple')
    await expect(optionsArea).toHaveValue(/application\/x-www-form-urlencoded/)
  })

  test('DB templates set tool type/name and params JSON', async ({ page }) => {
    await page.goto('/tools')
    await page.waitForLoadState('networkidle')

    const typeInput = page.getByPlaceholder('http_get')
    const nameInput = page.getByPlaceholder('simple')
    const paramsArea = page.getByPlaceholder('{"url":"https://example.com"}')

    // DB 模板（echo_int）
    await page.getByRole('button', { name: 'DB 模板' }).click()
    await expect(typeInput).toHaveValue('db_query')
    await expect(nameInput).toHaveValue('template')
    await expect(paramsArea).toHaveValue(/"template_id"\s*:\s*"echo_int"/)
    await expect(paramsArea).toHaveValue(/"sql"\s*:\s*"SELECT/)

    // DB echo_text
    await page.getByRole('button', { name: 'DB echo_text' }).click()
    await expect(typeInput).toHaveValue('db_query')
    await expect(nameInput).toHaveValue('template')
    await expect(paramsArea).toHaveValue(/"template_id"\s*:\s*"echo_text"/)

    // DB select_now
    await page.getByRole('button', { name: 'DB select_now' }).click()
    await expect(paramsArea).toHaveValue(/"template_id"\s*:\s*"select_now"/)

    // DB explain（在现有 params 上追加 explain: true）
    await page.getByRole('button', { name: 'DB explain' }).click()
    await expect(paramsArea).toHaveValue(/"explain"\s*:\s*true/)
  })

  test('按类型模板 根据 Type 字段应用模板', async ({ page }) => {
    await page.goto('/tools')
    await page.waitForLoadState('networkidle')

    const typeInput = page.getByPlaceholder('http_get')
    const paramsArea = page.getByPlaceholder('{"url":"https://example.com"}')

    // 将 Type 改为 http_post，然后点击“按类型模板”，应应用 POST 模板
    await typeInput.fill('http_post')
    await page.getByRole('button', { name: '按类型模板' }).click()
    await expect(paramsArea).toHaveValue(/httpbin\.org\/post/)

    // 将 Type 改为 db_query，然后点击“按类型模板”，应应用 DB 模板
    await typeInput.fill('db_query')
    await page.getByRole('button', { name: '按类型模板' }).click()
    await expect(paramsArea).toHaveValue(/"template_id"\s*:\s*"echo_int"/)
  })
})
