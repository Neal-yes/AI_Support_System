import { describe, it, expect } from 'vitest'
import { applyTpl, buildPromUrl, buildLogsUrl, isValidHttpUrl, type ObsCtx } from './obs'

describe('obs utils', () => {
  const ctx: ObsCtx = { tenant: 't1', type: 'http', name: 'search' }

  it('applyTpl replaces placeholders', () => {
    const tpl = 'sum(rate(x{tenant="$tenant",tool_type="$type",tool_name="$name",option_key="$key"}[5m]))'
    const out = applyTpl(tpl, ctx, 'timeout_ms')
    expect(out).toContain('tenant="t1"')
    expect(out).toContain('tool_type="http"')
    expect(out).toContain('tool_name="search"')
    expect(out).toContain('option_key="timeout_ms"')
  })

  it('applyTpl handles empty template and empty key gracefully', () => {
    const ctx: ObsCtx = { tenant: 't2', type: 'http', name: 'n' }
    // 空模板 -> 空字符串
    expect(applyTpl('', ctx, 'k')).toBe('')
    // 模板存在但 key 为空 -> 正确替换为空
    const out = applyTpl('x{tenant="$tenant",k="$key"}', ctx, '')
    expect(out).toContain('tenant="t2"')
    expect(out).toContain('k=""')
  })

  it('buildPromUrl/buildLogsUrl return null when base is empty', () => {
    const ctx: ObsCtx = { tenant: 't', type: 'x', name: 'y' }
    expect(buildPromUrl('', 'x', ctx, 'k')).toBeNull()
    expect(buildPromUrl(undefined as any, 'x', ctx, 'k')).toBeNull()
    expect(buildLogsUrl('', 'x', ctx, 'k')).toBeNull()
    expect(buildLogsUrl(undefined as any, 'x', ctx, 'k')).toBeNull()
  })

  it('buildPromUrl supports /graph param g0.expr', () => {
    const base = 'http://localhost:9090/graph'
    const url = buildPromUrl(base, 'x{tenant="$tenant",k="$key"}', ctx, 'k1')
    expect(url).not.toBeNull()
    const u = url as string
    expect(u).toContain('g0.expr=')
    const qs = decodeURIComponent(u.split('g0.expr=')[1])
    expect(qs).toContain('tenant="t1"')
    expect(qs).toContain('k="k1"')
  })

  it('buildPromUrl supports query param for API base', () => {
    const base = 'http://localhost:9090/api/v1/query'
    const url = buildPromUrl(base, 'x{tenant="$tenant",k="$key"}', ctx, 'k2')
    expect(url).not.toBeNull()
    expect(url!).toContain('query=')
  })

  it('buildPromUrl preserves existing query params', () => {
    const base = 'http://localhost:9090/graph?theme=dark'
    const url = buildPromUrl(base, 'x{tenant="$tenant"}', ctx, 'kk')
    expect(url).not.toBeNull()
    const u = url as string
    expect(u).toContain('theme=dark')
    expect(u).toContain('&g0.expr=')
  })

  it('buildLogsUrl builds q param and preserves existing', () => {
    const base = 'https://logs.example.com/search?from=now-1h'
    const url = buildLogsUrl(base, 'k:"$key" AND tenant:"$tenant"', ctx, 'timeout')
    expect(url).not.toBeNull()
    const u = url as string
    expect(u).toContain('from=now-1h')
    expect(u).toContain('&q=')
    const qs = decodeURIComponent(u.split('q=')[1])
    expect(qs).toContain('tenant:"t1"')
    expect(qs).toContain('k:"timeout"')
  })

  it('isValidHttpUrl validates http/https correctly', () => {
    expect(isValidHttpUrl('http://a.com')).toBe(true)
    expect(isValidHttpUrl('https://a.com/x?y=1')).toBe(true)
    expect(isValidHttpUrl('HTTP://UPPERCASE.COM')).toBe(true)
    expect(isValidHttpUrl('ws://a.com')).toBe(false)
    expect(isValidHttpUrl('ftp://a.com')).toBe(false)
    expect(isValidHttpUrl('')).toBe(false)
    expect(isValidHttpUrl(undefined)).toBe(false)
    expect(isValidHttpUrl(null as any)).toBe(false)
  })
})
