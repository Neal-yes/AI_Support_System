<template>
  <section class="card">
    <h2>Invoke Tool</h2>
    <form @submit.prevent="invoke">
      <div>
        <label>Tenant</label>
        <input v-model="tenant" placeholder="default" />
      </div>
      <div>
        <label>Type</label>
        <input v-model="toolType" placeholder="http_get" />
        <button type="button" style="margin-left:8px" @click="applyTemplateByType">按类型模板</button>
      </div>
      <div>
        <label>Name</label>
        <input v-model="toolName" placeholder="simple" />
      </div>
      <div>
        <label>Params (JSON)</label>
        <textarea v-model="paramsStr" rows="5" placeholder='{"url":"https://example.com"}' />
        <div class="row">
          <button type="button" @click="formatParams">格式化 Params</button>
          <button type="button" @click="setHttpGetTemplate">GET 模板</button>
          <button type="button" @click="setHttpPostTemplate">POST 模板</button>
          <button type="button" @click="setDbTemplate">DB 模板</button>
          <button type="button" @click="setHttpGetWithHeadersTemplate">GET+Headers</button>
          <button type="button" @click="setHttpPostTextTemplate">POST(Text)</button>
          <button type="button" @click="setHttpPostFormTemplate">POST(Form)</button>
          <button type="button" @click="setDbEchoTextTemplate">DB echo_text</button>
          <button type="button" @click="setDbSelectNowTemplate">DB select_now</button>
          <button type="button" @click="setDbExplainTemplate">DB explain</button>
        </div>
      </div>
      <div>
        <label>Options (JSON)</label>
        <textarea v-model="optionsStr" rows="5" placeholder='{"timeout_ms":2000, "allow_hosts":["example.com"], "deny_hosts":[]}' />
        <div class="row">
          <button type="button" @click="formatOptions">格式化 Options</button>
          <button type="button" @click="setOptionsDenyHosts">deny_hosts 示例</button>
          <button type="button" @click="setOptionsRateLimit">rate_limit 示例</button>
          <button type="button" @click="setOptionsCircuit">circuit 示例</button>
        </div>
      </div>
      <button type="submit">Invoke</button>
      <a style="margin-left:8px" href="/metrics" target="_blank">/metrics</a>
      <button type="button" style="margin-left:8px" @click="previewOptions">预览合并策略</button>
    </form>
    <h3>Request Preview</h3>
    <div class="row">
      <button type="button" @click="copy(requestPreview)">复制请求</button>
      <button type="button" @click="copy(curlPreview)">复制 cURL</button>
    </div>
    <pre>{{ requestPreview }}</pre>
    <h3>cURL</h3>
    <pre>{{ curlPreview }}</pre>
    <h3>Result <small v-if="status">(status={{ status }} duration={{ durationMs }}ms)</small></h3>
    <div v-if="errorHint" class="warn">{{ errorHint }}</div>
    <div v-if="headers && Object.keys(headers).length">
      <h4>Response Headers</h4>
      <pre>{{ headers }}</pre>
    </div>
    <div class="row">
      <button type="button" @click="copy(result)">复制结果</button>
    </div>
    <pre>{{ result }}</pre>
    <h3>Merged Options</h3>
    <pre>{{ mergedOptions }}</pre>
    <h3>Policy Layers (global/tenant/type/name/request)</h3>
    <pre>{{ policyLayers }}</pre>
    <h3>Policy Layers Diff</h3>
    <div class="row" style="gap:8px; align-items:center; flex-wrap: wrap;">
      <label>键名过滤：</label>
      <input v-model="filterKey" placeholder="输入关键字，如 allow/timeout" style="min-width:240px" />
      <label><input type="checkbox" v-model="showOverriddenOnly" /> 仅显示覆盖项</label>
      <details>
        <summary>列选择器</summary>
        <label><input type="checkbox" v-model="showCols.global" /> Global</label>
        <label><input type="checkbox" v-model="showCols.tenant" /> Tenant</label>
        <label><input type="checkbox" v-model="showCols.type" /> Type</label>
        <label><input type="checkbox" v-model="showCols.name" /> Name</label>
        <label><input type="checkbox" v-model="showCols.request" /> Request</label>
      </details>
      <details>
        <summary>观测链接</summary>
        <div class="obs-conf">
          <label>Prom 基地址：</label>
          <input v-model="promBase" placeholder="http://localhost:9090/graph 或 /api/v1/query" style="min-width:320px" />
          <span v-if="promBase && !promBaseValid" style="color:#c62828;font-size:12px;margin-left:6px">无效的 URL（需 http/https）</span>
          <label>查询模板：</label>
          <input v-model="promQueryTpl" style="min-width:420px" />
        </div>
        <div class="obs-conf">
          <label>日志基地址：</label>
          <input v-model="logsBase" placeholder="https://logs.example.com/search" style="min-width:320px" />
          <span v-if="logsBase && !logsBaseValid" style="color:#c62828;font-size:12px;margin-left:6px">无效的 URL（需 http/https）</span>
          <label>查询模板：</label>
          <input v-model="logsQueryTpl" placeholder='key:"$key" AND tenant:"$tenant" AND tool:"$type.$name"' style="min-width:420px" />
        </div>
        <div class="row" style="margin-top:6px">
          <button type="button" class="mini" @click="resetObsConf">重置观测配置</button>
        </div>
        <div class="row" style="margin-top:6px; gap:8px; align-items:center; flex-wrap:wrap">
          <button type="button" class="mini" @click="exportObsConf">导出配置</button>
          <button type="button" class="mini" @click="triggerImport">导入配置</button>
          <input ref="importInput" type="file" accept="application/json" style="display:none" @change="onImportFile" />
        </div>
        <div class="row" style="margin-top:6px; gap:8px; align-items:center; flex-wrap:wrap">
          <label>测试键名：</label>
          <input v-model="testKey" placeholder="例如 timeout_ms" style="min-width:200px" />
          <button type="button" class="mini" @click="openObsTest('metrics')"
            :disabled="metricsTestDisabled" :title="metricsTestTitle">测试打开指标</button>
          <button type="button" class="mini" @click="openObsTest('logs')"
            :disabled="logsTestDisabled" :title="logsTestTitle">测试打开日志</button>
        </div>
        <div class="obs-conf" style="margin-top:6px">
          <label>PromQL 预览：</label>
          <code style="white-space:pre-wrap">{{ promPreview }}</code>
        </div>
        <div class="obs-conf" style="margin-top:6px">
          <label>日志查询预览：</label>
          <code style="white-space:pre-wrap">{{ logsPreview }}</code>
        </div>
      </details>
      <details>
        <summary>预设筛选</summary>
        <label v-for="b in presetBadgeList" :key="b" class="preset-item">
          <input type="checkbox" v-model="selectedBadges[b]" />
          <span class="kbadge" :data-type="b">{{ b }}</span>
        </label>
      </details>
      <label>子键排序：</label>
      <input v-model="subSortExpr" placeholder="如 merged.retry_backoff_ms 或 allow_hosts.length" style="min-width:300px" />
      <label style="margin-left:8px"><input type="checkbox" v-model="useVirtual" /> 启用虚拟滚动</label>
      <span style="margin-left:8px">每页</span>
      <select v-model.number="pageSize">
        <option :value="20">20</option>
        <option :value="50">50</option>
        <option :value="100">100</option>
        <option :value="200">200</option>
      </select>
      
      <template v-if="!useVirtual">
        <button type="button" @click="goFirst" :disabled="page<=1">⏮</button>
        <button type="button" @click="goPrev" :disabled="page<=1">◀</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button type="button" @click="goNext" :disabled="page>=pageCount">▶</button>
        <button type="button" @click="goLast" :disabled="page>=pageCount">⏭</button>
        <span>（{{ fromIdx+1 }}-{{ toIdx }} / {{ filteredRows.length }}）</span>
      </template>
      <template v-else>
        <span style="margin-left:8px">高度</span>
        <input type="number" v-model.number="vsHeight" min="240" max="1200" style="width:90px" /> px
        <span>（共 {{ sortedRows.length }} 条）</span>
      </template>
      <button type="button" @click="exportMergedJSON">导出 merged.json</button>
      <button type="button" @click="exportLayersJSON">导出 layers.json</button>
      <button type="button" @click="exportDiffCSV">导出 diff.csv</button>
    </div>
    <div v-if="filteredRows.length === 0" style="margin-top:6px">暂无</div>
    <div class="layers-wrap" v-else :style="{ '--frozen-left': frozenLeftCss }">
    <div v-if="useVirtual" class="vs-wrap" :style="{height: vsHeight + 'px'}" @scroll="onVsScroll" ref="vsWrap">
      <table class="layers-table">
        <thead>
          <tr>
            <th class="col-key" ref="keyCol" @click="sortBy('key')">Key <span class="sort" v-if="sortKey==='key'">{{ sortAsc? '▲':'▼' }}</span></th>
            <th v-if="showCols.global">Global</th>
            <th v-if="showCols.tenant">Tenant</th>
            <th v-if="showCols.type">Type</th>
            <th v-if="showCols.name">Name</th>
            <th v-if="showCols.request">Request</th>
            <th class="col-merged" @click="sortBy('merged')">Merged <span class="sort" v-if="sortKey==='merged'">{{ sortAsc? '▲':'▼' }}</span></th>
            <th @click="sortBy('source')">Source <span class="sort" v-if="sortKey==='source'">{{ sortAsc? '▲':'▼' }}</span></th>
            <th @click="sortBy('overridden')">Overridden <span class="sort" v-if="sortKey==='overridden'">{{ sortAsc? '▲':'▼' }}</span></th>
            <th>Obs</th>
          </tr>
        </thead>
        <tbody>
          <tr aria-hidden="true" style="height: 0;">
            <td :style="{height: topPad + 'px', padding: 0, border: 0}" :colspan="colspanCount"></td>
          </tr>
          <tr v-for="r in visibleRows" :key="r.key" :class="{ overridden: r.overridden }">
            <td class="col-key">
              <div class="key-cell">
                <code>{{ r.key }}</code>
                <span v-for="b in keyBadges(r.key)" :key="b" class="kbadge" :data-type="b">{{ b }}</span>
              </div>
            </td>
            <td v-if="showCols.global">{{ r.global }}</td>
            <td v-if="showCols.tenant">{{ r.tenant }}</td>
            <td v-if="showCols.type">{{ r.type }}</td>
            <td v-if="showCols.name">{{ r.name }}</td>
            <td v-if="showCols.request">{{ r.request }}</td>
            <td class="col-merged">
              <div class="merged-cell">
                <b>{{ r.merged }}</b>
                <span class="type-badge">{{ typeOfValRaw(r.merged) }}</span>
                <button class="mini" title="复制 merged" @click="copy(r.merged)">复制</button>
                <button v-if="typeOfValRaw(r.merged) === 'Array' || typeOfValRaw(r.merged) === 'Object'" class="mini" @click="toggleExpand(r.key)">{{ expanded.has(r.key) ? '收起' : '展开' }}</button>
              </div>
              <pre v-if="expanded.has(r.key)" class="expanded-json">{{ prettyMerged(r.key) }}</pre>
            </td>
            <td><span class="src" :data-src="r.source">{{ r.source }}</span></td>
            <td>{{ r.overridden ? 'Yes' : '' }}</td>
            <td>
              <button class="mini" @click="openObs(r,'metrics')" :disabled="!promBase">指标</button>
              <button class="mini" @click="openObs(r,'logs')" :disabled="!logsBase">日志</button>
            </td>
          </tr>
          <tr aria-hidden="true" style="height: 0;">
            <td :style="{height: bottomPad + 'px', padding: 0, border: 0}" :colspan="colspanCount"></td>
          </tr>
        </tbody>
      </table>
    </div>
    <table v-else class="layers-table">
      <thead>
        <tr>
          <th class="col-key" ref="keyCol" @click="sortBy('key')">Key <span class="sort" v-if="sortKey==='key'">{{ sortAsc? '▲':'▼' }}</span></th>
          <th v-if="showCols.global">Global</th>
          <th v-if="showCols.tenant">Tenant</th>
          <th v-if="showCols.type">Type</th>
          <th v-if="showCols.name">Name</th>
          <th v-if="showCols.request">Request</th>
          <th class="col-merged" @click="sortBy('merged')">Merged <span class="sort" v-if="sortKey==='merged'">{{ sortAsc? '▲':'▼' }}</span></th>
          <th @click="sortBy('source')">Source <span class="sort" v-if="sortKey==='source'">{{ sortAsc? '▲':'▼' }}</span></th>
          <th @click="sortBy('overridden')">Overridden <span class="sort" v-if="sortKey==='overridden'">{{ sortAsc? '▲':'▼' }}</span></th>
          <th>Obs</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in displayedRows" :key="r.key" :class="{ overridden: r.overridden }">
          <td class="col-key">
            <div class="key-cell">
              <code>{{ r.key }}</code>
              <span v-for="b in keyBadges(r.key)" :key="b" class="kbadge" :data-type="b">{{ b }}</span>
            </div>
          </td>
          <td v-if="showCols.global">{{ r.global }}</td>
          <td v-if="showCols.tenant">{{ r.tenant }}</td>
          <td v-if="showCols.type">{{ r.type }}</td>
          <td v-if="showCols.name">{{ r.name }}</td>
          <td v-if="showCols.request">{{ r.request }}</td>
          <td class="col-merged">
            <div class="merged-cell">
              <b>{{ r.merged }}</b>
              <span class="type-badge">{{ typeOfValRaw(r.merged) }}</span>
              <button class="mini" title="复制 merged" @click="copy(r.merged)">复制</button>
              <button v-if="typeOfValRaw(r.merged) === 'Array' || typeOfValRaw(r.merged) === 'Object'" class="mini" @click="toggleExpand(r.key)">{{ expanded.has(r.key) ? '收起' : '展开' }}</button>
            </div>
            <pre v-if="expanded.has(r.key)" class="expanded-json">{{ prettyMerged(r.key) }}</pre>
          </td>
          <td><span class="src" :data-src="r.source">{{ r.source }}</span></td>
          <td>{{ r.overridden ? 'Yes' : '' }}</td>
          <td>
            <button class="mini" @click="openObs(r,'metrics')" :disabled="!promBase">指标</button>
            <button class="mini" @click="openObs(r,'logs')" :disabled="!logsBase">日志</button>
          </td>
        </tr>
      </tbody>
    </table>
    </div>
    <h3>调用历史</h3>
    <div v-if="history.length === 0">暂无</div>
    <ul>
      <li v-for="(h, idx) in history" :key="idx">
        <code>{{ h.time }}</code>
        <span> — {{ h.tenant_id }}/{{ h.tool_type }}.{{ h.tool_name }} — status={{ h.status }} duration={{ h.durationMs }}ms</span>
        <button type="button" @click="restore(h)">恢复</button>
      </li>
    </ul>
  </section>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, nextTick, onBeforeUnmount, watch } from 'vue'
import axios from 'axios'
import { isValidHttpUrl } from '../utils/obs'

const tenant = ref('default')
const toolType = ref('http_get')
const toolName = ref('simple')
const paramsStr = ref('{"url":"https://example.com"}')
const optionsStr = ref('{"timeout_ms":2000, "allow_hosts":["example.com"], "deny_hosts":[]}')
const result = ref('')
const status = ref<number | undefined>(undefined)
const durationMs = ref<number | undefined>(undefined)
const headers = ref<Record<string, any>>({})
const errorHint = ref('')
const mergedOptions = ref('')
const policyLayers = ref('')
const policyLayersDiff = ref('')
const mergedObj = ref<Record<string, any>>({})
const layersObj = ref<Record<string, any>>({})
type Row = { key: string; global: string; tenant: string; type: string; name: string; request: string; merged: string; source: string; overridden: boolean }

// Persist observability config to localStorage
const OBS_LS_KEY = 'toolsObsConf'
function loadObsConf() {
  try {
    const raw = localStorage.getItem(OBS_LS_KEY)
    if (!raw) {
      if (ENV_PROM_BASE) promBase.value = ENV_PROM_BASE
      if (ENV_PROM_QUERY_TPL) promQueryTpl.value = ENV_PROM_QUERY_TPL
      if (ENV_LOGS_BASE) logsBase.value = ENV_LOGS_BASE
      if (ENV_LOGS_QUERY_TPL) logsQueryTpl.value = ENV_LOGS_QUERY_TPL
      return
    }
    const obj = JSON.parse(raw)
    if (typeof obj?.promBase === 'string') promBase.value = obj.promBase
    if (typeof obj?.promQueryTpl === 'string' && obj.promQueryTpl) promQueryTpl.value = obj.promQueryTpl
    if (typeof obj?.logsBase === 'string') logsBase.value = obj.logsBase
    if (typeof obj?.logsQueryTpl === 'string' && obj.logsQueryTpl) logsQueryTpl.value = obj.logsQueryTpl
  } catch {}
}
function saveObsConf() {
  try {
    const obj = {
      promBase: promBase.value,
      promQueryTpl: promQueryTpl.value,
      logsBase: logsBase.value,
      logsQueryTpl: logsQueryTpl.value,
    }
    localStorage.setItem(OBS_LS_KEY, JSON.stringify(obj))
  } catch {}
}

function resetObsConf() {
  try { localStorage.removeItem(OBS_LS_KEY) } catch {}
  promBase.value = ENV_PROM_BASE || ''
  promQueryTpl.value = ENV_PROM_QUERY_TPL || 'sum(rate(tool_invocations_total{tenant="$tenant",tool_type="$type",tool_name="$name",option_key="$key"}[5m]))'
  logsBase.value = ENV_LOGS_BASE || ''
  logsQueryTpl.value = ENV_LOGS_QUERY_TPL || 'key:"$key" AND tenant:"$tenant" AND tool:"$type.$name"'
}

function exportObsConf() {
  try {
    const obj = {
      promBase: promBase.value,
      promQueryTpl: promQueryTpl.value,
      logsBase: logsBase.value,
      logsQueryTpl: logsQueryTpl.value,
      version: 1,
      exportedAt: new Date().toISOString(),
    }
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'toolsObsConf.json'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {}
}

function triggerImport() {
  importInput.value?.click()
}

const MAX_IMPORT_SIZE = 1024 * 1024 // 1MB 上限，防止异常大文件拖垮页面

function onImportFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files && input.files[0]
  if (!file) return
  if (file.size > MAX_IMPORT_SIZE) {
    alert(`导入配置失败：文件过大（${Math.ceil(file.size/1024)}KB），上限为 ${Math.ceil(MAX_IMPORT_SIZE/1024)}KB`)
    input.value = ''
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const text = String(reader.result || '')
      const obj = JSON.parse(text)
      if (obj && typeof obj === 'object') {
        if (typeof obj.promBase === 'string') promBase.value = obj.promBase
        if (typeof obj.promQueryTpl === 'string' && obj.promQueryTpl) promQueryTpl.value = obj.promQueryTpl
        if (typeof obj.logsBase === 'string') logsBase.value = obj.logsBase
        if (typeof obj.logsQueryTpl === 'string' && obj.logsQueryTpl) logsQueryTpl.value = obj.logsQueryTpl
        saveObsConf()
      }
    } catch (e:any) {
      const msg = (e?.message || 'JSON 解析错误')
      alert('导入配置失败：' + msg)
    }
    finally {
      input.value = ''
    }
  }
  reader.readAsText(file)
}
const policyRows = ref<Row[]>([])
const showCols = ref({ global: true, tenant: true, type: true, name: true, request: true })
const expanded = ref<Set<string>>(new Set())
const keyCol = ref<HTMLElement | null>(null)
const frozenLeft = ref(240)
const frozenLeftCss = computed(() => `${frozenLeft.value}px`)
// virtual scroll
const useVirtual = ref(false)
const vsHeight = ref(420)
const rowHeight = 38 // approximate single-row height
const buffer = 8
const vsWrap = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const visibleCount = computed(() => Math.max(1, Math.ceil(vsHeight.value / rowHeight) + buffer))
const startIndex = computed(() => Math.max(0, Math.floor(scrollTop.value / rowHeight) - Math.floor(buffer/2)))
const endIndex = computed(() => Math.min(sortedRows.value.length, startIndex.value + visibleCount.value))
const visibleRows = computed(() => sortedRows.value.slice(startIndex.value, endIndex.value))
const topPad = computed(() => startIndex.value * rowHeight)
const bottomPad = computed(() => Math.max(0, (sortedRows.value.length - endIndex.value) * rowHeight))
const colspanCount = computed(() => 1 + (showCols.value.global?1:0) + (showCols.value.tenant?1:0) + (showCols.value.type?1:0) + (showCols.value.name?1:0) + (showCols.value.request?1:0) + 4)
function onVsScroll(e: Event) {
  const t = e.target as HTMLElement
  scrollTop.value = t.scrollTop
}
const filterKey = ref('')
const showOverriddenOnly = ref(false)
const presetBadgeList = ['allow','deny','timeout','rate','retry','circuit','cache','resp'] as const
const selectedBadges = ref<Record<string, boolean>>({
  allow: false, deny: false, timeout: false, rate: false, retry: false, circuit: false, cache: false, resp: false,
})
const filteredRows = computed(() => {
  const kw = (filterKey.value || '').toLowerCase().trim()
  const activeBadges = Object.keys(selectedBadges.value).filter(k => (selectedBadges.value as any)[k])
  return policyRows.value.filter(r => {
    const okKw = !kw || r.key.toLowerCase().includes(kw)
    const okOv = !showOverriddenOnly.value || r.overridden
    const rowBadges = keyBadges(r.key)
    const okBadge = activeBadges.length === 0 || activeBadges.some(b => rowBadges.includes(b))
    return okKw && okOv && okBadge
  })
})
// pagination
const page = ref(1)
const pageSize = ref(50)
const pageCount = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize.value)))
const fromIdx = computed(() => Math.min((page.value - 1) * pageSize.value, Math.max(0, filteredRows.value.length - 1)))
const toIdx = computed(() => Math.min(fromIdx.value + pageSize.value, filteredRows.value.length))
watch([filterKey, showOverriddenOnly], () => { page.value = 1 })
const sortKey = ref<'key'|'source'|'merged'|'overridden'>('key')
const sortAsc = ref(true)
const subSortExpr = ref('')
const sortedRows = computed(() => {
  const arr = [...filteredRows.value]
  const k = sortKey.value
  arr.sort((a,b) => {
    let av: any, bv: any
    if (k === 'overridden') {
      av = a.overridden ? 1 : 0
      bv = b.overridden ? 1 : 0
    } else if (k === 'merged' && subSortExpr.value.trim()) {
      av = getSubSortVal(a, subSortExpr.value.trim())
      bv = getSubSortVal(b, subSortExpr.value.trim())
    } else {
      av = (a as any)[k]
      bv = (b as any)[k]
    }
    // numeric compare if both numeric
    const an = Number(av), bn = Number(bv)
    let cmp
    if (!Number.isNaN(an) && !Number.isNaN(bn)) cmp = an - bn
    else cmp = String(av).localeCompare(String(bv))
    return sortAsc.value ? cmp : -cmp
  })
  return arr
})
function sortBy(k: 'key'|'source'|'merged'|'overridden') {
  if (sortKey.value === k) sortAsc.value = !sortAsc.value
  else { sortKey.value = k; sortAsc.value = true }
}
const displayedRows = computed(() => {
  if (useVirtual.value) return sortedRows.value
  return sortedRows.value.slice(fromIdx.value, toIdx.value)
})
function goFirst(){ page.value = 1 }
function goPrev(){ if (page.value > 1) page.value -= 1 }
function goNext(){ if (page.value < pageCount.value) page.value += 1 }
function goLast(){ page.value = pageCount.value }
type HistoryItem = {
  time: string
  tenant_id: string
  tool_type: string
  tool_name: string
  params: any
  options: any
  status: number | undefined
  durationMs: number | undefined
}
const history = ref<HistoryItem[]>([])

// Observability links configuration
const promBase = ref('')
const promQueryTpl = ref('sum(rate(tool_invocations_total{tenant="$tenant",tool_type="$type",tool_name="$name",option_key="$key"}[5m]))')
const logsBase = ref('')
const logsQueryTpl = ref('key:"$key" AND tenant:"$tenant" AND tool:"$type.$name"')
const importInput = ref<HTMLInputElement | null>(null)

// Environment-provided defaults (Vite: VITE_*)
const ENV_PROM_BASE = (import.meta as any).env?.VITE_OBS_PROM_BASE || ''
const ENV_PROM_QUERY_TPL = (import.meta as any).env?.VITE_OBS_PROM_QUERY_TPL || ''
const ENV_LOGS_BASE = (import.meta as any).env?.VITE_OBS_LOGS_BASE || ''
const ENV_LOGS_QUERY_TPL = (import.meta as any).env?.VITE_OBS_LOGS_QUERY_TPL || ''

// Template preview/test controls
const testKey = ref('')

function applyTplWithKey(tpl: string, key: string): string {
  try {
    return tpl
      .replace(/\$tenant/g, tenant.value)
      .replace(/\$type/g, toolType.value)
      .replace(/\$name/g, toolName.value)
      .replace(/\$key/g, key)
  } catch { return tpl }
}
const promPreview = computed(() => {
  const key = (testKey.value || '').trim()
  if (!key || !promQueryTpl.value) return ''
  return applyTplWithKey(promQueryTpl.value, key)
})
const logsPreview = computed(() => {
  const key = (testKey.value || '').trim()
  if (!key || !logsQueryTpl.value) return ''
  return applyTplWithKey(logsQueryTpl.value, key)
})

function applyTpl(tpl: string, r: Row): string {
  return tpl
    .replace(/\$tenant/g, tenant.value)
    .replace(/\$type/g, toolType.value)
    .replace(/\$name/g, toolName.value)
    .replace(/\$key/g, r.key)
}

function openObs(r: Row, kind: 'metrics'|'logs') {
  try {
    if (kind === 'metrics') {
      if (!promBase.value) return
      const q = applyTpl(promQueryTpl.value || '', r)
      const hasGraph = /\/graph(\b|$)/.test(promBase.value)
      const url = promBase.value + (promBase.value.includes('?') ? '&' : '?') + (hasGraph ? 'g0.expr=' : 'query=') + encodeURIComponent(q)
      window.open(url, '_blank')
    } else {
      if (!logsBase.value) return
      const q = applyTpl(logsQueryTpl.value || '', r)
      const url = logsBase.value + (logsBase.value.includes('?') ? '&' : '?') + 'q=' + encodeURIComponent(q)
      window.open(url, '_blank')
    }
  } catch {}
}

function openObsTest(kind: 'metrics'|'logs') {
  try {
    const key = (testKey.value || '').trim()
    if (!key) return
    if (kind === 'metrics') {
      if (!promBase.value || !promBaseValid.value) {
        alert('Prom 基地址为空或格式无效（需以 http/https 开头）')
        return
      }
      const q = promPreview.value
      if (!q) return
      const hasGraph = /\/graph(\b|$)/.test(promBase.value)
      const url = promBase.value + (promBase.value.includes('?') ? '&' : '?') + (hasGraph ? 'g0.expr=' : 'query=') + encodeURIComponent(q)
      window.open(url, '_blank')
    } else {
      if (!logsBase.value || !logsBaseValid.value) {
        alert('日志基地址为空或格式无效（需以 http/https 开头）')
        return
      }
      const q = logsPreview.value
      if (!q) return
      const url = logsBase.value + (logsBase.value.includes('?') ? '&' : '?') + 'q=' + encodeURIComponent(q)
      window.open(url, '_blank')
    }
  } catch {}
}

// URL validation and disabled reasons
const promBaseValid = computed(() => !promBase.value || isValidHttpUrl(promBase.value))
const logsBaseValid = computed(() => !logsBase.value || isValidHttpUrl(logsBase.value))
const metricsTestDisabled = computed(() => !testKey.value || !promBase.value || !promBaseValid.value)
const logsTestDisabled = computed(() => !testKey.value || !logsBase.value || !logsBaseValid.value)
const metricsTestTitle = computed(() => {
  if (!testKey.value) return '请输入测试键名'
  if (!promBase.value) return '请填写 Prom 基地址'
  if (!promBaseValid.value) return 'Prom 基地址需以 http/https 开头'
  return ''
})
const logsTestTitle = computed(() => {
  if (!testKey.value) return '请输入测试键名'
  if (!logsBase.value) return '请填写日志基地址'
  if (!logsBaseValid.value) return '日志基地址需以 http/https 开头'
  return ''
})

const requestPreview = computed(() => {
  try {
    const params = JSON.parse(paramsStr.value || '{}')
    const options = JSON.parse(optionsStr.value || '{}')
    const body = {
      tenant_id: tenant.value,
      tool_type: toolType.value,
      tool_name: toolName.value,
      params,
      options
    }
    return JSON.stringify(body, null, 2)
  } catch (e:any) {
    return 'JSON 解析错误: ' + (e?.message || String(e))
  }
})

const curlPreview = computed(() => {
  try {
    const data = requestPreview.value
    if (data.startsWith('JSON 解析错误')) return data
    return `curl -sS -X POST -H 'Content-Type: application/json' --data '${data.replace(/'/g, "'\\''")}' ${window.location.origin}/api/v1/tools/invoke`
  } catch (e:any) {
    return ''
  }
})

async function invoke() {
  try {
    status.value = undefined
    durationMs.value = undefined
    headers.value = {}
    errorHint.value = ''
    const params = JSON.parse(paramsStr.value || '{}')
    const options = JSON.parse(optionsStr.value || '{}')
    const start = performance.now()
    const resp = await axios.post('/api/v1/tools/invoke', {
      tenant_id: tenant.value,
      tool_type: toolType.value,
      tool_name: toolName.value,
      params,
      options
    })
    result.value = JSON.stringify(resp.data, null, 2)
    status.value = resp.status
    durationMs.value = Math.round(performance.now() - start)
    headers.value = resp.headers || {}
    saveHistory({ params, options })
  } catch (e:any) {
    if (axios.isAxiosError(e)) {
      const status = e.response?.status
      const data = e.response?.data
      result.value = `AxiosError status=${status}\n` + (data ? JSON.stringify(data, null, 2) : String(e.message))
      durationMs.value = durationMs.value ?? undefined
      headers.value = (e.response && e.response.headers) || {}
      deriveErrorHint(data)
      try {
        const params = JSON.parse(paramsStr.value || '{}')
        const options = JSON.parse(optionsStr.value || '{}')
        saveHistory({ params, options, status: status })
      } catch {}
    } else {
      result.value = String(e?.message || e)
    }
  }
}

function buildRows(layers: Record<string, any>, merged: Record<string, any>): Row[] {
  try {
    const order = ['global', 'tenant', 'type', 'name', 'request']
    const keys = new Set<string>()
    for (const k of Object.keys(merged || {})) keys.add(k)
    for (const l of order) for (const k of Object.keys((layers && layers[l]) || {})) keys.add(k)
    const rows: Row[] = []
    for (const k of Array.from(keys).sort()) {
      const g = val((layers && layers.global) ? layers.global[k] : undefined)
      const t = val((layers && layers.tenant) ? layers.tenant[k] : undefined)
      const ty = val((layers && layers.type) ? layers.type[k] : undefined)
      const n = val((layers && layers.name) ? layers.name[k] : undefined)
      const r = val((layers && layers.request) ? layers.request[k] : undefined)
      const m = val(merged ? merged[k] : undefined)
      let source = 'global'
      for (const l of order) {
        if (layers && layers[l] && Object.prototype.hasOwnProperty.call(layers[l], k)) source = l
      }
      const overridden = (source !== 'global') && order.slice(0, order.indexOf(source)).some(l => layers && layers[l] && Object.prototype.hasOwnProperty.call(layers[l], k))
      rows.push({ key: k, global: g, tenant: t, type: ty, name: n, request: r, merged: m, source, overridden })
    }
    return rows
  } catch { return [] }
}

function setOptionsRateLimit() {
  try {
    const opts = JSON.parse(optionsStr.value || '{}')
    const merged = { rate_limit_per_sec: 2, retry_max: 1, retry_backoff_ms: 200 }
    optionsStr.value = JSON.stringify({ ...opts, ...merged }, null, 2)
  } catch {}
}

function setOptionsCircuit() {
  try {
    const opts = JSON.parse(optionsStr.value || '{}')
    const merged = { circuit_threshold: 2, circuit_cooldown_ms: 8000 }
    optionsStr.value = JSON.stringify({ ...opts, ...merged }, null, 2)
  } catch {}
}

function setOptionsDenyHosts() {
  try {
    const opts = JSON.parse(optionsStr.value || '{}')
    const merged = { deny_hosts: ['bad.com', 'malicious.example'], allow_hosts: ['example.com'] }
    optionsStr.value = JSON.stringify({ ...opts, ...merged }, null, 2)
  } catch {}
}

function formatParams() {
  try { paramsStr.value = JSON.stringify(JSON.parse(paramsStr.value || '{}'), null, 2) } catch {}
}
function formatOptions() {
  try { optionsStr.value = JSON.stringify(JSON.parse(optionsStr.value || '{}'), null, 2) } catch {}
}
function setHttpGetTemplate() {
  paramsStr.value = JSON.stringify({ url: 'https://example.com' }, null, 2)
}
function setHttpPostTemplate() {
  paramsStr.value = JSON.stringify({ url: 'https://httpbin.org/post', body: { hello: 'world' } }, null, 2)
}

function setDbTemplate() {
  // db_query.template 要求：params.template_id、params.params(dict)、可选 params.explain，且网关执行需提供 params.sql
  const tpl = {
    template_id: 'echo_int',
    sql: 'SELECT %(x)s::int AS x',
    params: { x: 1 },
    explain: false
  }
  paramsStr.value = JSON.stringify(tpl, null, 2)
  toolType.value = 'db_query'
  toolName.value = 'template'
}

function setHttpGetWithHeadersTemplate() {
  paramsStr.value = JSON.stringify({ url: 'https://example.com', headers: { 'User-Agent': 'ToolGateway/1.0', 'X-Debug': '1' } }, null, 2)
  toolType.value = 'http_get'
  toolName.value = 'simple'
}

function setHttpPostTextTemplate() {
  paramsStr.value = JSON.stringify({ url: 'https://httpbin.org/post', body: 'raw text body' }, null, 2)
  toolType.value = 'http_post'
  toolName.value = 'simple'
  try {
    const opts = JSON.parse(optionsStr.value || '{}')
    optionsStr.value = JSON.stringify({ ...opts, content_type: 'text/plain' }, null, 2)
  } catch {}
}

function setHttpPostFormTemplate() {
  paramsStr.value = JSON.stringify({ url: 'https://httpbin.org/post', body: { a: 1, b: 'x' } }, null, 2)
  toolType.value = 'http_post'
  toolName.value = 'simple'
  try {
    const opts = JSON.parse(optionsStr.value || '{}')
    optionsStr.value = JSON.stringify({ ...opts, content_type: 'application/x-www-form-urlencoded' }, null, 2)
  } catch {}
}

function setDbEchoTextTemplate() {
  const tpl = {
    template_id: 'echo_text',
    sql: "SELECT %(txt)s::text AS txt",
    params: { txt: 'hello' },
    explain: false
  }
  paramsStr.value = JSON.stringify(tpl, null, 2)
  toolType.value = 'db_query'
  toolName.value = 'template'
}

function setDbSelectNowTemplate() {
  const tpl = {
    template_id: 'select_now',
    sql: 'SELECT NOW() as ts',
    params: {},
    explain: false
  }
  paramsStr.value = JSON.stringify(tpl, null, 2)
  toolType.value = 'db_query'
  toolName.value = 'template'
}

function setDbExplainTemplate() {
  try {
    const p = JSON.parse(paramsStr.value || '{}')
    p.explain = true
    if (!p.sql) p.sql = 'SELECT %(x)s::int AS x'
    if (!p.params) p.params = { x: 1 }
    paramsStr.value = JSON.stringify(p, null, 2)
  } catch {
    setDbTemplate()
    try {
      const p = JSON.parse(paramsStr.value || '{}')
      p.explain = true
      paramsStr.value = JSON.stringify(p, null, 2)
    } catch {}
  }
  toolType.value = 'db_query'
  toolName.value = 'template'
}

function applyTemplateByType() {
  const t = (toolType.value || '').toLowerCase()
  if (t.includes('db')) {
    setDbTemplate()
  } else if (t.includes('post')) {
    setHttpPostTemplate()
  } else {
    setHttpGetTemplate()
  }
}

async function previewOptions() {
  try {
    const params = JSON.parse(paramsStr.value || '{}')
    const options = JSON.parse(optionsStr.value || '{}')
    const resp = await axios.post('/api/v1/tools/preview', {
      tenant_id: tenant.value,
      tool_type: toolType.value,
      tool_name: toolName.value,
      params,
      options
    })
    const data = resp.data || {}
    mergedOptions.value = JSON.stringify(data.merged_options ?? data.mergedOptions ?? data, null, 2)
    policyLayers.value = JSON.stringify(data.layers ?? {}, null, 2)
    mergedObj.value = (data.merged_options ?? {})
    layersObj.value = (data.layers ?? {})
    policyLayersDiff.value = buildLayersDiff(layersObj.value, mergedObj.value)
    policyRows.value = buildRows(layersObj.value, mergedObj.value)
  } catch (e:any) {
    const fallback = axios.isAxiosError(e) && e.response?.data ? JSON.stringify(e.response.data, null, 2) : String(e?.message || e)
    mergedOptions.value = fallback
    policyLayers.value = ''
    mergedObj.value = {}
    layersObj.value = {}
    policyLayersDiff.value = ''
    policyRows.value = []
  }
}

function buildLayersDiff(layers: Record<string, any>, merged: Record<string, any>): string {
  try {
    const order = ['global', 'tenant', 'type', 'name', 'request']
    const keys = new Set<string>()
    for (const k of Object.keys(merged || {})) keys.add(k)
    for (const layer of order) {
      const obj = (layers && layers[layer]) || {}
      for (const k of Object.keys(obj)) keys.add(k)
    }
    const lines: string[] = []
    for (const k of Array.from(keys).sort()) {
      const vals = order.map(l => (layers && layers[l] && Object.prototype.hasOwnProperty.call(layers[l], k)) ? layers[l][k] : undefined)
      const mergedVal = merged?.[k]
      let source = 'global'
      for (const l of order) {
        if (layers && layers[l] && Object.prototype.hasOwnProperty.call(layers[l], k)) source = l
      }
      const overridden = vals.slice(0, order.indexOf(source)).some(v => v !== undefined)
      lines.push(`${k}: merged=${JSON.stringify(mergedVal)} | source=${source}${overridden ? ' (overrode earlier layer)' : ''}`)
    }
    return lines.join('\n') || '(no keys)'
  } catch (e:any) {
    return '(diff build error) ' + (e?.message || String(e))
  }
}

// Helpers used by table rendering and export
function val(v: any): string {
  if (v === undefined) return ''
  try { return typeof v === 'string' ? v : JSON.stringify(v) } catch { return String(v) }
}

function typeOfValRaw(s: string): string {
  if (s === '') return 'Undefined'
  try {
    const parsed = JSON.parse(s)
    if (parsed === null) return 'Null'
    if (Array.isArray(parsed)) return 'Array'
    const t = typeof parsed
    if (t === 'number') return 'Number'
    if (t === 'boolean') return 'Bool'
    if (t === 'string') return 'String'
    if (t === 'object') return 'Object'
    return t
  } catch { return 'String' }
}

function exportMergedJSON() {
  try { downloadBlob(new Blob([JSON.stringify(mergedObj.value, null, 2)], { type: 'application/json' }), 'merged.json') } catch {}
}
function exportLayersJSON() {
  try { downloadBlob(new Blob([JSON.stringify(layersObj.value, null, 2)], { type: 'application/json' }), 'layers.json') } catch {}
}
function exportDiffCSV() {
  try {
    const cols: Array<{ key: keyof Row; name: string; cond?: boolean }> = [
      { key: 'key', name: 'key' },
      { key: 'global', name: 'global', cond: showCols.value.global },
      { key: 'tenant', name: 'tenant', cond: showCols.value.tenant },
      { key: 'type', name: 'type', cond: showCols.value.type },
      { key: 'name', name: 'name', cond: showCols.value.name },
      { key: 'request', name: 'request', cond: showCols.value.request },
      { key: 'merged', name: 'merged' },
      { key: 'source', name: 'source' },
      { key: 'overridden', name: 'overridden' },
    ]
    const enabled = cols.filter(c => c.cond === undefined || c.cond)
    const header = enabled.map(c => c.name)
    const rows = sortedRows.value.map(r => enabled.map(c => c.key === 'overridden' ? String((r as any)[c.key]) : (r as any)[c.key]))
    const csv = [header.join(','), ...rows.map(cols => cols.map(csvEsc).join('\n'.includes(',') ? ',' : ',')).map(line => line)].join('\n')
    downloadBlob(new Blob([csv], { type: 'text/csv;charset=utf-8;' }), 'diff.csv')
  } catch {}
}
function csvEsc(s: string): string {
  if (s == null) return ''
  const needs = /[",\n]/.test(s)
  const t = s.replace(/\"/g, '""').replace(/"/g, '""')
  return needs ? `"${s.replace(/"/g, '""')}"` : s
}
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function copy(text: string) {
  const t = typeof text === 'string' ? text : String(text)
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t)
  } else {
    const el = document.createElement('textarea')
    el.value = t
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
  }
}

function deriveErrorHint(data: any) {
  try {
    const detail: string = (data && (data.detail || data.message)) || ''
    if (!detail) return
    const lower = detail.toLowerCase()
    if (lower.includes('allow_hosts')) {
      errorHint.value = '命中 allow_hosts 策略：请在请求 options.allow_hosts 或策略文件中添加对应主机名（仅主机名，忽略协议/端口）'
    } else if (lower.includes('deny_hosts')) {
      errorHint.value = '命中 deny_hosts 策略：该主机被拒绝，移除或调整策略中的 deny_hosts 配置'
    } else {
      errorHint.value = ''
    }
  } catch { errorHint.value = '' }
}

function saveHistory(extra: { params: any; options: any; status?: number }) {
  const item: HistoryItem = {
    time: new Date().toLocaleString(),
    tenant_id: tenant.value,
    tool_type: toolType.value,
    tool_name: toolName.value,
    params: extra.params,
    options: extra.options,
    status: extra.status ?? status.value,
    durationMs: durationMs.value
  }
  const list = [item, ...history.value].slice(0, 20)
  history.value = list
  try { localStorage.setItem('toolsHistory', JSON.stringify(list)) } catch {}
}

function loadHistory() {
  try {
    const raw = localStorage.getItem('toolsHistory')
    if (raw) history.value = JSON.parse(raw)
  } catch {}
}

function restore(h: HistoryItem) {
  tenant.value = h.tenant_id
  toolType.value = h.tool_type
  toolName.value = h.tool_name
  paramsStr.value = JSON.stringify(h.params, null, 2)
  optionsStr.value = JSON.stringify(h.options, null, 2)
}

onMounted(loadHistory)
onMounted(loadObsConf)
watch([promBase, promQueryTpl, logsBase, logsQueryTpl], () => { saveObsConf() })
// dynamic frozen offset
onMounted(() => {
  const recalc = () => {
    try {
      if (keyCol.value) {
        const w = keyCol.value.getBoundingClientRect().width
        // add border gap
        frozenLeft.value = Math.max(200, Math.round(w) + 16)
      }
    } catch {}
  }
  recalc()
  window.addEventListener('resize', recalc)
  const obs = new MutationObserver(recalc)
  if (keyCol.value) obs.observe(keyCol.value, { attributes: true, childList: true, subtree: true })
  onBeforeUnmount(() => { window.removeEventListener('resize', recalc); obs.disconnect() })
})

function toggleExpand(k: string) {
  const s = new Set(expanded.value)
  if (s.has(k)) {
    s.delete(k)
  } else {
    s.add(k)
  }
  expanded.value = s
}
function prettyMerged(k: string) {
  try { return JSON.stringify((mergedObj.value as any)[k], null, 2) } catch { return '' }
}

function keyBadges(k: string): string[] {
  const key = k.toLowerCase()
  const badges: string[] = []
  if (/(^|[_\.])allow(_|$)|allow_hosts|whitelist/.test(key)) badges.push('allow')
  if (/(^|[_\.])deny(_|$)|deny_hosts|blacklist/.test(key)) badges.push('deny')
  if (/timeout/.test(key)) badges.push('timeout')
  if (/\brate(_limit|limit|_per_sec|persec|_per_min|permin)?\b/.test(key)) badges.push('rate')
  if (/^retry|[_\.]retry/.test(key)) badges.push('retry')
  if (/^circuit|[_\.]circuit|breaker/.test(key)) badges.push('circuit')
  if (/cache/.test(key)) badges.push('cache')
  if (/resp(_max_chars|onse|_size|size)/.test(key)) badges.push('resp')
  return badges
}

function getSubSortVal(r: Row, expr: string): any {
  // try parse merged value per row
  let mv: any
  try { mv = JSON.parse(r.merged) } catch { mv = r.merged }
  const parts = expr.split('.').filter(Boolean)
  const getByPath = (root: any, ps: string[]) => {
    let v = root
    for (const p of ps) {
      if (v == null) return undefined
      if (p === 'length' && (typeof v === 'string' || Array.isArray(v))) { v = v.length; continue }
      v = v[p as any]
    }
    return v
  }
  // 1) merged.<path> => use global merged object
  if (parts[0] === 'merged') {
    return getByPath(mergedObj.value, parts.slice(1))
  }
  // 2) try on row's merged value (if object)
  const valOnRow = getByPath(mv, parts)
  if (valOnRow !== undefined) return valOnRow
  // 3) try on global merged object directly
  const valOnGlobal = getByPath(mergedObj.value, parts)
  if (valOnGlobal !== undefined) return valOnGlobal
  // 4) fallback: numeric parse if possible
  const num = Number(r.merged)
  return Number.isNaN(num) ? r.merged : num
}
</script>


<style scoped>
.layers-wrap { overflow: auto; max-width: 100%; }
.layers-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 6px;
  font-size: 13px;
}
.layers-table th, .layers-table td {
  border: 1px solid #e5e7eb;
  padding: 6px 8px;
  vertical-align: top;
}
.layers-table thead th {
  background: #f9fafb;
  position: sticky;
  top: 0;
  z-index: 1;
}
.layers-table .col-key {
  position: sticky;
  left: 0;
  background: #ffffff;
  min-width: 220px;
  max-width: 360px;
}
.layers-table .col-merged {
  position: sticky;
  left: var(--frozen-left, 240px);
  background: #ffffff;
  min-width: 260px;
}
.expanded-json { margin: 6px 0 0; max-height: 220px; overflow: auto; background: #f8fafc; border: 1px solid #e5e7eb; padding: 6px 8px; }
tr.overridden { background: #fff7ed; }
.sort { color:#6b7280; font-size:12px; margin-left:4px; }
.merged-cell { display:flex; gap:8px; align-items:center; }
.type-badge { font-size:11px; padding:2px 6px; border-radius:10px; background:#eef2ff; color:#3730a3; }
.mini { font-size:11px; padding:2px 6px; }
.src[data-src="request"] { color: #0ea5e9; font-weight: 600; }
.src[data-src="name"] { color: #a855f7; font-weight: 600; }
.src[data-src="type"] { color: #10b981; font-weight: 600; }
.src[data-src="tenant"] { color: #f59e0b; font-weight: 600; }
.src[data-src="global"] { color: #6b7280; font-weight: 600; }

/* Key badges */
.key-cell { display:flex; gap:8px; align-items:center; flex-wrap: wrap; }
.kbadge { font-size:10px; padding:2px 6px; border-radius:999px; border:1px solid transparent; text-transform: uppercase; letter-spacing: .3px; }
.kbadge[data-type="allow"] { background:#ecfdf5; color:#065f46; border-color:#a7f3d0; }
.kbadge[data-type="deny"] { background:#fef2f2; color:#991b1b; border-color:#fecaca; }
.kbadge[data-type="timeout"] { background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe; }
.kbadge[data-type="rate"] { background:#eef2ff; color:#3730a3; border-color:#c7d2fe; }
.kbadge[data-type="retry"] { background:#f5f3ff; color:#6d28d9; border-color:#ddd6fe; }
.kbadge[data-type="circuit"] { background:#fff7ed; color:#9a3412; border-color:#fed7aa; }
.kbadge[data-type="cache"] { background:#f0fdf4; color:#166534; border-color:#bbf7d0; }
.kbadge[data-type="resp"] { background:#faf5ff; color:#7c3aed; border-color:#e9d5ff; }
</style>


