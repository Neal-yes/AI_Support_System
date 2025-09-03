<template>
  <section class="card">
    <h2>{{ t('title') }}</h2>
    <form @submit.prevent="startStream">
      <div class="row">
        <label>{{ t('lang') }}</label>
        <select v-model="locale">
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
      </div>
      <div class="row">
        <label>{{ t('query') }}</label>
        <input v-model="query" :placeholder="t('queryPlaceholder')" />
      </div>
      <div class="row">
        <label>{{ t('ragLabel') }}</label>
        <input type="checkbox" v-model="useRag" />
        <small class="hint">{{ t('ragHint') }}</small>
      </div>
      <div class="row"><small class="hint">{{ t('ragImpact') }}</small></div>
      <div class="row warn" v-if="useRag"><span>{{ t('ragWarn') }}</span></div>
      <div class="row" v-if="useRag"><small class="hint">{{ t('thresholdTip') }}</small></div>

      <div class="preflight" v-if="useRag">
        <div class="preflight-title">
          <span>{{ t('preflightTitle') }}</span>
          <button type="button" class="retry" :disabled="preflightLoading" @click="runPreflight">{{ t('retry') }}</button>
        </div>
        <div class="preflight-body">
          <span v-if="preflightLoading">{{ t('preflightLoading') }}</span>
          <template v-else>
            <div v-if="preflight && preflight.ok === false" class="preflight-error">
              {{ t('preflightErr', { err: preflightError || 'unknown' }) }}
            </div>
            <span v-if="preflightState === 'good'">{{ t('preflightGood', { max: fmtScore(preflight.max_score), avg: fmtScore(preflight.avg_score) }) }}</span>
            <span v-else-if="preflightState === 'weak'">{{ t('preflightWeak', { max: fmtScore(preflight.max_score), avg: fmtScore(preflight.avg_score) }) }}</span>
            <span v-else>{{ t('preflightNoHit') }}</span>
          </template>
        </div>
      </div>

      <div class="row">
        <label>{{ t('heartbeat') }}</label>
        <input type="number" v-model.number="heartbeatMs" min="0" step="100" />
      </div>
      <div class="row">
        <label>{{ t('timeLimit') }}</label>
        <input type="number" v-model.number="timeLimitMs" min="0" step="500" />
      </div>
      <div class="row">
        <label>{{ t('numPredict') }}</label>
        <input type="number" v-model.number="numPredict" min="1" step="1" />
      </div>
      <div class="row">
        <button type="submit" :disabled="loading">{{ t('start') }}</button>
        <button type="button" @click="stopStream" :disabled="!loading">{{ t('stop') }}</button>
        <span class="status" :data-on="loading">{{ statusText }}</span>
      </div>
    </form>

    <pre class="output">{{ output }}</pre>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const query = ref('请简要回答（两句话内）')
const useRag = ref(false)
const heartbeatMs = ref(2000)
const timeLimitMs = ref(60000)
const numPredict = ref(8)

const loading = ref(false)
const output = ref('')
const status = ref<'idle' | 'started' | 'streaming' | 'done' | 'error'>('idle')

let controller: AbortController | null = null
let idleTimer: number | undefined
const statusText = computed(() => {
  if (status.value === 'idle') return 'idle'
  if (status.value === 'started') return 'started'
  if (status.value === 'streaming') return 'streaming'
  if (status.value === 'done') return 'done'
  return 'error'
})

// i18n
const { t, locale } = useI18n()

function resetIdleTimer() {
  if (idleTimer) window.clearTimeout(idleTimer)
  // 容忍度建议 >= heartbeat * 3; 若未启用心跳则给一个较大的值
  const ms = heartbeatMs.value && heartbeatMs.value > 0 ? heartbeatMs.value * 3 : 20000
  idleTimer = window.setTimeout(() => {
    appendLine('[client] idle-timeout, aborting stream')
    stopStream()
  }, ms)
}

function appendLine(line: string) {
  output.value += (output.value ? '\n' : '') + line
}

// 恢复用户上次选择的 RAG 开关
onMounted(() => {
  try {
    const savedLang = localStorage.getItem('lang') as 'zh' | 'en' | null
    if (savedLang === 'zh' || savedLang === 'en') {
      locale.value = savedLang
    }
    const saved = localStorage.getItem('useRag')
    if (saved !== null) {
      useRag.value = saved === '1'
    }
  } catch {}
})

// 持久化用户的 RAG 选择
watch(useRag, (v) => {
  try {
    localStorage.setItem('useRag', v ? '1' : '0')
  } catch {}
})

watch(locale, (v) => {
  try { localStorage.setItem('lang', v) } catch {}
})

// RAG 预检（基于后端检索结果动态提示）
type Preflight = { ok: boolean; error?: string; contexts_count: number; ctx_total_len: number; max_score: number | null; avg_score: number | null }
const preflight = ref<Preflight>({ ok: true, contexts_count: 0, ctx_total_len: 0, max_score: null, avg_score: null })
const preflightLoading = ref(false)
const preflightState = ref<'none' | 'good' | 'weak'>('none')
const preflightError = ref('')
let preflightTimer: number | undefined

function fmtScore(v: number | null | undefined) {
  return typeof v === 'number' ? v.toFixed(2) : '—'
}

async function runPreflight() {
  if (!useRag.value) { preflightState.value = 'none'; return }
  const q = (query.value || '').trim()
  if (q.length < 2) { preflightState.value = 'none'; return }
  preflightLoading.value = true
  try {
    const resp = await fetch('/api/v1/rag/preflight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q })
    })
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    const data = await resp.json()
    preflight.value = data
    if (data && data.ok === false) {
      preflightError.value = data.error || ''
      preflightState.value = 'none'
      return
    } else {
      preflightError.value = ''
    }
    // 简单阈值：上下文长度与相似度
    const ctxOK = (data?.ctx_total_len || 0) >= 80 && (data?.contexts_count || 0) > 0
    const scoreMax = typeof data?.max_score === 'number' ? data.max_score : 0
    if (ctxOK && scoreMax >= 0.7) preflightState.value = 'good'
    else if (ctxOK) preflightState.value = 'weak'
    else preflightState.value = 'none'
  } catch (e: any) {
    preflightState.value = 'none'
    preflightError.value = e?.message || String(e || '')
  } finally {
    preflightLoading.value = false
  }
}

function schedulePreflight() {
  if (preflightTimer) window.clearTimeout(preflightTimer)
  preflightTimer = window.setTimeout(runPreflight, 500)
}

watch([useRag, query], () => schedulePreflight())

async function startStream() {
  if (loading.value) return
  output.value = ''
  status.value = 'idle'

  const body: any = {
    query: query.value,
    use_rag: useRag.value,
    options: {
      num_predict: numPredict.value
    }
  }
  if (heartbeatMs.value && heartbeatMs.value > 0) body.options.heartbeat_ms = heartbeatMs.value
  if (timeLimitMs.value && timeLimitMs.value > 0) body.options.time_limit_ms = timeLimitMs.value

  controller = new AbortController()
  loading.value = true
  status.value = 'started'
  resetIdleTimer()

  try {
    const resp = await fetch('/api/v1/ask/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify(body),
      signal: controller.signal
    })
    if (!resp.ok || !resp.body) {
      throw new Error('HTTP ' + resp.status)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value, { stream: true })
      buf += chunk

      // 按 SSE 事件分隔 \n\n
      let idx: number
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const event = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        handleSseEvent(event)
      }
    }
    // flush 残余（通常不会有完整事件）
    if (buf.trim().length) handleSseEvent(buf)

    status.value = 'done'
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      appendLine('[client] aborted')
    } else {
      appendLine('[client] error: ' + (e?.message || String(e)))
      status.value = 'error'
    }
  } finally {
    loading.value = false
    if (idleTimer) window.clearTimeout(idleTimer)
  }
}

function handleSseEvent(raw: string) {
  // 只解析以 data: 开头的行，忽略其他头部
  const lines = raw.split('\n')
  for (const line of lines) {
    if (!line.startsWith('data:')) continue
    const payload = line.slice(5).trimStart()
    // 处理控制事件
    if (payload === '[started]') {
      status.value = 'streaming'
      resetIdleTimer()
      continue
    }
    if (payload === '[heartbeat]') {
      // 仅用于保活与重置超时，不展示
      resetIdleTimer()
      continue
    }
    if (payload === '[done]') {
      status.value = 'done'
      appendLine('[done]')
      if (controller) controller.abort()
      return
    }

    // 普通内容
    appendLine(payload)
    resetIdleTimer()
  }
}

function stopStream() {
  if (controller) {
    controller.abort()
    controller = null
  }
  loading.value = false
}

onBeforeUnmount(() => {
  stopStream()
  if (idleTimer) window.clearTimeout(idleTimer)
  if (preflightTimer) window.clearTimeout(preflightTimer)
})
</script>

<style scoped>
.row { display: flex; gap: 8px; align-items: center; margin: 6px 0; }
label { width: 130px; color: #666; }
input[type="text"], input[type="number"] { flex: 1; padding: 6px 8px; }
button { margin-right: 8px; }
.status { margin-left: 8px; font-size: 12px; color: #999; }
.status[data-on="true"] { color: #2e7d32; }
.output { margin-top: 12px; white-space: pre-wrap; min-height: 120px; background: #0b1020; color: #e0e6f0; padding: 10px; border-radius: 6px; }
small.hint { color: #888; }
.row.warn { color: #b45309; background: #fff7ed; border: 1px solid #fde68a; padding: 6px 8px; border-radius: 4px; }
.preflight { border: 1px dashed #cbd5e1; padding: 8px; border-radius: 6px; background: #f8fafc; margin: 6px 0; }
.preflight-title { font-weight: 600; color: #334155; margin-bottom: 4px; display: flex; align-items: center; justify-content: space-between; }
.preflight-body { color: #475569; }
.preflight-error { color: #b45309; background: #fff7ed; border: 1px solid #fde68a; padding: 6px 8px; border-radius: 4px; margin-bottom: 6px; }
.preflight-title .retry { font-size: 12px; padding: 4px 8px; border: 1px solid #94a3b8; background: #fff; color: #334155; border-radius: 4px; cursor: pointer; }
.preflight-title .retry:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
