import { createI18n } from 'vue-i18n'

const saved = ((): 'zh' | 'en' => {
  try {
    const v = localStorage.getItem('lang') as 'zh' | 'en' | null
    if (v === 'zh' || v === 'en') return v
  } catch {}
  return 'zh'
})()

export const messages = {
  zh: {
    title: 'Ask Stream（含心跳保活）',
    lang: '语言',
    query: '问题',
    queryPlaceholder: '请输入问题',
    ragLabel: '启用知识库检索（RAG）',
    ragHint: '默认关闭以获得更快响应',
    ragWarn: '提示：CPU 环境下启用 RAG 可能显著变慢（完整回复约需 ~50s）。',
    ragImpact: '开启后可提升相关性，但响应更慢、失败率更高；关闭更快更稳但可能少量偏离事实。',
    thresholdTip: '建议仅在“高置信检索命中”时启用（相似度 ≥ 0.70，检索文本总长度 ≥ 80 字）。',
    heartbeat: 'Heartbeat (ms)',
    timeLimit: 'Time Limit (ms)',
    numPredict: 'num_predict',
    start: '开始',
    stop: '停止',
    preflightTitle: 'RAG 预检提示',
    preflightLoading: '正在评估检索相关性…',
    preflightGood: '检索命中较高（max: {max}, avg: {avg}），建议可启用 RAG。',
    preflightWeak: '检索命中较弱（max: {max}, avg: {avg}），不建议启用 RAG。',
    preflightNoHit: '未检索到可用上下文，不建议启用 RAG。',
    preflightErr: '预检暂不可用：{err}',
    retry: '重试',
    health: {
      overall: '总体',
      services: {
        postgres: 'Postgres',
        redis: 'Redis',
        qdrant: 'Qdrant',
        ollama: 'Ollama',
      },
      status: {
        ready: '就绪',
        degraded: '降级',
        error: '错误',
        checking: '检查中',
      },
    },
  },
  en: {
    title: 'Ask Stream (with Heartbeat)',
    lang: 'Language',
    query: 'Query',
    queryPlaceholder: 'Type your question',
    ragLabel: 'Enable Knowledge Retrieval (RAG)',
    ragHint: 'Disabled by default for faster response',
    ragWarn: 'Note: On CPU, enabling RAG can be much slower (~50s to finish).',
    ragImpact: 'Enabling may improve relevance but increases latency and failure risk; disabling is faster and steadier but may reduce factuality.',
    thresholdTip: 'Recommend enabling only on high-confidence retrieval (similarity ≥ 0.70 and retrieved text length ≥ 80 chars).',
    heartbeat: 'Heartbeat (ms)',
    timeLimit: 'Time Limit (ms)',
    numPredict: 'num_predict',
    start: 'Start',
    stop: 'Stop',
    preflightTitle: 'RAG Preflight',
    preflightLoading: 'Evaluating retrieval confidence…',
    preflightGood: 'Hits look strong (max: {max}, avg: {avg}). RAG is recommended.',
    preflightWeak: 'Hits look weak (max: {max}, avg: {avg}). RAG is not recommended.',
    preflightNoHit: 'No useful contexts found. RAG is not recommended.',
    preflightErr: 'Preflight unavailable: {err}',
    retry: 'Retry',
    health: {
      overall: 'overall',
      services: {
        postgres: 'Postgres',
        redis: 'Redis',
        qdrant: 'Qdrant',
        ollama: 'Ollama',
      },
      status: {
        ready: 'ready',
        degraded: 'degraded',
        error: 'error',
        checking: 'checking',
      },
    },
  },
}

export const i18n = createI18n({
  legacy: false,
  locale: saved,
  fallbackLocale: 'en',
  messages,
})
