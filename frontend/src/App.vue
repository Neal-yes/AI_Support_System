<template>
  <main class="container">
    <header class="topbar">
      <h1>AI Support System</h1>
      <nav>
        <RouterLink to="/">Home</RouterLink>
        <RouterLink to="/tools">Tools</RouterLink>
        <RouterLink to="/db">DB</RouterLink>
      </nav>
      <div class="ver" :title="`version: ${appVersion}`">{{ appVersion }}</div>
      <div class="health" @mouseenter="showHealth()" @mouseleave="hideHealth()">
        <span class="dot" :data-status="healthStatus"></span>
        <small class="label">{{ healthLabel }}</small>
        <div v-if="healthOpen" class="health-pop">
          <div class="row"><b>{{ t('health.overall') }}:</b> <span :data-s="healthStatus">{{ healthLabel }}</span></div>
          <div class="row" v-for="(svc, name) in healthDetail.services" :key="name">
            <b>{{ serviceLabel(name as string) }}:</b>
            <span :data-s="svc.healthy ? 'ok' : 'down'">{{ svc.healthy ? 'ok' : 'down' }}</span>
          </div>
        </div>
      </div>
    </header>
    <RouterView />
  </main>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
// Import version from package.json (Vite + TS resolveJsonModule enabled)
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import pkg from '../package.json'

type Health = 'loading' | 'ok' | 'degraded' | 'error'
const healthStatus = ref<Health>('loading')
let timer: number | undefined
const healthOpen = ref(false)
const healthDetail = ref<any>({ services: {} })
const { t } = useI18n()

const appVersion: string = ((import.meta as any).env?.VITE_APP_VERSION as string) || (pkg?.version as string) || '0.0.0'

const healthLabel = computed(() => {
  switch (healthStatus.value) {
    case 'ok': return t('health.status.ready')
    case 'degraded': return t('health.status.degraded')
    case 'error': return t('health.status.error')
    case 'loading': default: return t('health.status.checking')
  }
})

async function pingReady() {
  const ctrl = new AbortController()
  const id = window.setTimeout(() => ctrl.abort(), 2500)
  try {
    const r = await fetch('/api/-/ready', { signal: ctrl.signal })
    if (!r.ok) { healthStatus.value = 'error'; return }
    const j = await r.json()
    healthStatus.value = j?.status === 'ok' ? 'ok' : 'degraded'
  } catch {
    healthStatus.value = 'error'
  } finally {
    clearTimeout(id)
  }
}

async function showHealth() {
  healthOpen.value = true
  // Fetch detailed health only when opened
  try {
    const r = await fetch('/api/health')
    if (r.ok) {
      const j = await r.json()
      healthDetail.value = j
    }
  } catch {}
}

function hideHealth() {
  healthOpen.value = false
}

function serviceLabel(name: string): string {
  const key = `health.services.${name}`
  const v = t(key) as string
  return v === key ? name : v
}

onMounted(() => {
  pingReady()
  timer = window.setInterval(pingReady, 10000) as unknown as number
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.container { max-width: 980px; margin: 0 auto; padding: 24px; }
.topbar { display:flex; gap:16px; align-items:center; justify-content:space-between; }
.topbar nav a { margin-right: 12px; }
.health { display:flex; align-items:center; gap:6px; position: relative; }
.dot { width: 10px; height: 10px; border-radius: 50%; display:inline-block; background:#9ca3af; }
.dot[data-status="loading"] { background:#9ca3af; }
.dot[data-status="ok"] { background:#16a34a; }
.dot[data-status="degraded"] { background:#f59e0b; }
.dot[data-status="error"] { background:#dc2626; }
.label { color:#64748b; }
.health-pop { position:absolute; top: 120%; right: 0; background: #0b1020; color: #e0e6f0; border: 1px solid #1f2937; padding: 8px 10px; border-radius: 6px; min-width: 220px; z-index: 10; }
.health-pop .row { display:flex; justify-content: space-between; gap: 10px; font-size: 12px; }
.health-pop [data-s="ok"] { color:#16a34a; }
.health-pop [data-s="down"] { color:#dc2626; }
.health-pop [data-s="loading"] { color:#9ca3af; }
.health-pop [data-s="degraded"] { color:#f59e0b; }
/* Version chip */
.ver { font-size: 12px; color:#94a3b8; border:1px solid #1f2937; padding:2px 6px; border-radius: 6px; }
</style>
