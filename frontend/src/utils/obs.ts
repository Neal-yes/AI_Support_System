export type ObsCtx = {
  tenant: string
  type: string
  name: string
}

// Lightweight URL validator for http/https schemes
export function isValidHttpUrl(u: string | null | undefined): boolean {
  if (!u) return false
  return /^https?:\/\//i.test(u)
}

export function applyTpl(tpl: string, ctx: ObsCtx, key: string): string {
  return (tpl || '')
    .replace(/\$tenant/g, ctx.tenant)
    .replace(/\$type/g, ctx.type)
    .replace(/\$name/g, ctx.name)
    .replace(/\$key/g, key)
}

export function buildPromUrl(base: string, queryTpl: string, ctx: ObsCtx, key: string): string | null {
  if (!base) return null
  const q = applyTpl(queryTpl || '', ctx, key)
  const hasGraph = /\/graph(\b|$)/.test(base)
  const param = hasGraph ? 'g0.expr=' : 'query='
  const sep = base.includes('?') ? '&' : '?'
  return base + sep + param + encodeURIComponent(q)
}

export function buildLogsUrl(base: string, queryTpl: string, ctx: ObsCtx, key: string): string | null {
  if (!base) return null
  const q = applyTpl(queryTpl || '', ctx, key)
  const sep = base.includes('?') ? '&' : '?'
  return base + sep + 'q=' + encodeURIComponent(q)
}
