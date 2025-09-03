import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'

// Helpers
async function openObsSection(page) {
  // 确保 <details> 打开：若未打开则点击 summary，若已打开则不再点击
  const details = page.locator('details', { hasText: '观测链接' }).first()
  await details.waitFor({ state: 'visible' })
  const isOpen = await details.evaluate((el: HTMLDetailsElement) => el.open)
  if (!isOpen) {
    await page.locator('summary', { hasText: '观测链接' }).first().click()
    await expect(details).toHaveAttribute('open', '')
  }
}

async function stubWindowOpen(page) {
  await page.addInitScript(() => {
    (window as any).__opened = []
    const orig = window.open
    window.open = (url?: string | URL | undefined, target?: string) => {
      ;(window as any).__opened.push({ url: String(url), target })
      return null as any
    }
    ;(window as any).__origOpen = orig
  })
}

async function getOpened(page) {
  return await page.evaluate(() => (window as any).__opened || [])
}

// Generic helper: safely set input value even if not visible (WebKit-friendly)
async function safeFill(page: any, loc: any, value: string) {
  try {
    await loc.scrollIntoViewIfNeeded()
    if (await loc.isVisible()) {
      await loc.fill(value)
      return
    }
  } catch {}
  const handle = await loc.elementHandle()
  if (handle) {
    await handle.evaluate((el, v: string) => {
      (el as HTMLInputElement).value = v
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }, value)
  }
}

test.describe('Tools 观测配置 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await stubWindowOpen(page)
  })

  test('非法/合法 URL、按钮状态与生成链接', async ({ page }) => {
    // 进入 /tools
    await page.goto('/tools')

    // 展开观测链接区域
    await openObsSection(page)

    const promInput = page.locator('xpath=//label[contains(normalize-space(.),"Prom 基地址")]/following-sibling::input[1]')
    const logsInput = page.locator('xpath=//label[contains(normalize-space(.),"日志基地址")]/following-sibling::input[1]')
    const keyInput = page.locator('xpath=//label[contains(normalize-space(.),"测试键名")]/following-sibling::input[1]')
    const btnMetrics = page.getByRole('button', { name: '测试打开指标' })
    const btnLogs = page.getByRole('button', { name: '测试打开日志' })

    // Step 1: 非法 URL
    await promInput.fill('ftp://x')
    await logsInput.fill('ws://a')
    await keyInput.fill('timeout_ms')

    await expect(btnMetrics).toBeDisabled()
    await expect(btnLogs).toBeDisabled()

    // 读取 title 提示（通过 attribute）
    await expect(btnMetrics).toHaveAttribute('title', /http\/https/)
    await expect(btnLogs).toHaveAttribute('title', /http\/https/)

    // Step 2: 合法 URL 并点击
    await promInput.fill('http://localhost:9090/graph')
    await logsInput.fill('https://logs.example.com/search')

    await expect(btnMetrics).toBeEnabled()
    await expect(btnLogs).toBeEnabled()

    await btnMetrics.click()
    await btnLogs.click()

    const opened = await getOpened(page)

    // 断言生成的链接包含预期参数
    const metricsUrl: string | undefined = opened.find((o: any) => String(o.url).includes('localhost:9090/graph'))?.url
    const logsUrl: string | undefined = opened.find((o: any) => String(o.url).includes('logs.example.com/search'))?.url

    expect(metricsUrl, '应生成 Prom g0.expr 参数').toMatch(/g0\.expr=/)
    expect(decodeURIComponent(metricsUrl!), 'PromQL 应包含 tenant/type/name/key').toMatch(/tenant="default"/)

    expect(logsUrl, '应生成日志 q= 参数').toMatch(/\bq=/)
    expect(decodeURIComponent(logsUrl!), '日志查询中包含 key/tenant/type.name').toMatch(/key:"timeout_ms".*tenant:"default".*tool:"http_get\.simple"/)
  })

  test('导入配置后字段回填与按钮联动', async ({ page }) => {
    await page.goto('/tools')
    await openObsSection(page)

    const promInput = page.locator('xpath=//label[contains(normalize-space(.),"Prom 基地址")]/following-sibling::input[1]')
    const logsInput = page.locator('xpath=//label[contains(normalize-space(.),"日志基地址")]/following-sibling::input[1]')
    const keyInput = page.locator('xpath=//label[contains(normalize-space(.),"测试键名")]/following-sibling::input[1]')
    const btnMetrics = page.getByRole('button', { name: '测试打开指标' })
    const btnLogs = page.getByRole('button', { name: '测试打开日志' })

    // 提前填写测试键名以便导入后立即联动（兼容 WebKit 隐藏场景）
    await safeFill(page, keyInput, 'timeout_ms')

    // 直接对隐藏的 input[type=file] 设置文件
    const confPath = path.resolve(process.cwd(), '../docs/assets/toolsObsConf.json')
    await page.setInputFiles('input[type="file"][accept="application/json"]', confPath)

    // 断言字段被回填
    await expect(promInput).toHaveValue('http://localhost:9090')
    await expect(logsInput).toHaveValue('https://logs.example.com/search')

    // 按钮应启用
    await expect(btnMetrics).toBeEnabled()
    await expect(btnLogs).toBeEnabled()

    // 点击并校验生成链接
    await btnMetrics.click()
    await btnLogs.click()
    const opened = await getOpened(page)
    const metricsUrl: string | undefined = opened.find((o: any) => String(o.url).includes('localhost:9090'))?.url
    const logsUrl: string | undefined = opened.find((o: any) => String(o.url).includes('logs.example.com/search'))?.url
    expect(metricsUrl).toBeTruthy()
    // 导入的 promBase 没有 /graph，应使用 query=
    expect(metricsUrl!).toMatch(/\bquery=/)
    expect(decodeURIComponent(metricsUrl!)).toMatch(/tenant="default"/)
    expect(logsUrl!).toMatch(/\bq=/)
    expect(decodeURIComponent(logsUrl!)).toMatch(/key:"timeout_ms".*tenant:"default".*tool:"http_get\.simple"/)
  })

  test('导出配置 JSON 内容正确', async ({ page }) => {
    await page.goto('/tools')
    await openObsSection(page)

    const promInput = page.locator('xpath=//label[contains(normalize-space(.),"Prom 基地址")]/following-sibling::input[1]')
    const logsInput = page.locator('xpath=//label[contains(normalize-space(.),"日志基地址")]/following-sibling::input[1]')
    const promTpl = page.locator('xpath=(//label[contains(normalize-space(.),"查询模板")]/following-sibling::input[1])[1]')
    const logsTpl = page.locator('xpath=//div[@class="obs-conf"][2]//label[contains(normalize-space(.),"查询模板")]/following-sibling::input[1]')

    // Helper: 兼容 WebKit 不可见场景，直接设置值并触发 input
    const setValue = async (loc: any, value: string) => {
      try {
        await loc.scrollIntoViewIfNeeded()
        if (await loc.isVisible()) {
          await loc.fill(value)
          return
        }
      } catch {}
      const handle = await loc.elementHandle()
      await page.evaluate((el, v) => {
        (el as HTMLInputElement).value = v
        el.dispatchEvent(new Event('input', { bubbles: true }))
        el.dispatchEvent(new Event('change', { bubbles: true }))
      }, handle, value)
    }

    // 设置已知值
    await setValue(promInput, 'http://127.0.0.1:9090')
    await setValue(promTpl, 'sum(rate(x_total{tenant="$tenant",tool_type="$type",tool_name="$name",option_key="$key"}[1m]))')
    await setValue(logsInput, 'https://logs.example.com/search')
    await setValue(logsTpl, 'key:"$key" AND tenant:"$tenant" AND tool:"$type.$name"')

    // 点击导出并捕获下载
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: '导出配置' }).click(),
    ])

    const tmpFile = path.join(os.tmpdir(), `toolsObsConf-${Date.now()}.json`)
    await download.saveAs(tmpFile)
    const content = fs.readFileSync(tmpFile, 'utf8')
    const obj = JSON.parse(content)

    expect(obj.promBase).toBe('http://127.0.0.1:9090')
    expect(obj.logsBase).toBe('https://logs.example.com/search')
    expect(obj.promQueryTpl).toMatch(/sum\(rate\(x_total/)
    expect(obj.logsQueryTpl).toMatch(/key:\"\$key\"/)
    expect(obj.version).toBe(1)
    expect(typeof obj.exportedAt).toBe('string')
    expect(obj.exportedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })

  test('导出（空字段）结构与文件名正确', async ({ page }) => {
    await page.goto('/tools')
    await openObsSection(page)

    // 点击重置观测配置，确保空字段/默认模板
    await page.getByRole('button', { name: '重置观测配置' }).click()

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: '导出配置' }).click(),
    ])

    // 文件名应为 toolsObsConf.json
    expect(download.suggestedFilename()).toBe('toolsObsConf.json')

    const tmpFile = path.join(os.tmpdir(), `toolsObsConf-empty-${Date.now()}.json`)
    await download.saveAs(tmpFile)
    const content = fs.readFileSync(tmpFile, 'utf8')
    const obj = JSON.parse(content)

    expect(typeof obj.promBase).toBe('string')
    expect(typeof obj.logsBase).toBe('string')
    expect(typeof obj.promQueryTpl).toBe('string')
    expect(typeof obj.logsQueryTpl).toBe('string')
    expect(obj.version).toBe(1)
    expect(obj.exportedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })

  test('导入无效 JSON 给出错误提示', async ({ page }) => {
    await page.goto('/tools')
    await openObsSection(page)

    // 准备无效 JSON 文件
    const badPath = path.join(os.tmpdir(), `bad-toolsObs-${Date.now()}.json`)
    fs.writeFileSync(badPath, '{bad:', 'utf8')

    const dialogPromise = page.waitForEvent('dialog')
    await page.setInputFiles('input[type="file"][accept="application/json"]', badPath)
    const dialog = await dialogPromise
    expect(dialog.message()).toContain('导入配置失败')
    await dialog.accept()
  })

  test('模板特殊字符与超长字符串 导出/导入 一致性', async ({ page }) => {
    await page.goto('/tools')
    await openObsSection(page)

    const promInput = page.locator('xpath=//label[contains(normalize-space(.),"Prom 基地址")]/following-sibling::input[1]')
    const logsInput = page.locator('xpath=//label[contains(normalize-space(.),"日志基地址")]/following-sibling::input[1]')
    const promTpl = page.locator('xpath=(//label[contains(normalize-space(.),"查询模板")]/following-sibling::input[1])[1]')
    const logsTpl = page.locator('xpath=//div[@class="obs-conf"][2]//label[contains(normalize-space(.),"查询模板")]/following-sibling::input[1]')

    // 构造包含特殊字符与超长内容的模板
    const basePromTpl = 'sum(rate(http_requests_total{tenant="$tenant",tool_type="$type",tool_name="$name",option_key="$key",path="/api/v1/search",method="GET",code=~"2.."}[1m])) by (code) / ignoring(instance) sum(rate(up{job="api"}[1m]))'
    const longSuffix = 'X'.repeat(5000)
    const promTplVal = basePromTpl + longSuffix
    const logsTplVal = 'key:"$key" AND tenant:"$tenant" AND tool:"$type.$name" AND msg:"a \"quoted\" value with \\backslash\\ and symbols !@#$%^&*()[]{}|;:,.<>?~"'

    await safeFill(page, promInput, 'http://127.0.0.1:9090')
    await safeFill(page, logsInput, 'https://logs.example.com/search')
    await safeFill(page, promTpl, promTplVal)
    await safeFill(page, logsTpl, logsTplVal)

    // 导出并校验内容与文件大小
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: '导出配置' }).click(),
    ])
    expect(download.suggestedFilename()).toBe('toolsObsConf.json')
    const tmpFile = path.join(os.tmpdir(), `toolsObsConf-long-${Date.now()}.json`)
    await download.saveAs(tmpFile)
    const content = fs.readFileSync(tmpFile, 'utf8')
    expect(content.length).toBeGreaterThan(1000)
    const obj = JSON.parse(content)
    expect(obj.promQueryTpl).toBe(promTplVal)
    expect(obj.logsQueryTpl).toBe(logsTplVal)

    // 重置后导入，断言回填与原值一致
    await page.getByRole('button', { name: '重置观测配置' }).click()
    await page.setInputFiles('input[type="file"][accept="application/json"]', tmpFile)

    // 等待导入异步完成并断言值完全一致（内置重试，兼容异步 FileReader）
    await expect(promTpl).toHaveValue(promTplVal)
    await expect(logsTpl).toHaveValue(logsTplVal)
  })
})
