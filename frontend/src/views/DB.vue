<template>
  <section class="card">
    <h2>DB Template Query</h2>
    <form @submit.prevent="execTpl">
      <div>
        <label>Template ID</label>
        <input v-model="tplId" placeholder="echo_int" />
      </div>
      <div>
        <label>Template Version</label>
        <input v-model="tplVer" placeholder="(optional, e.g. v1)" />
      </div>
      <div>
        <label>Params (JSON)</label>
        <textarea v-model="paramsStr" rows="5" placeholder='{"x": 123}' />
      </div>
      <div>
        <label>Explain</label>
        <input type="checkbox" v-model="explain" />
      </div>
      <button type="submit">Execute</button>
    </form>
    <pre>{{ result }}</pre>
  </section>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import axios from 'axios'

const tplId = ref('echo_int')
const tplVer = ref('')
const paramsStr = ref('{"x": 123}')
const explain = ref(false)
const result = ref('')

async function execTpl() {
  try {
    const params = JSON.parse(paramsStr.value || '{}')
    const payload:any = { template_id: tplId.value, params, explain: explain.value }
    if (tplVer.value && tplVer.value.trim()) payload.template_version = tplVer.value.trim()
    const { data } = await axios.post('/api/v1/db/query_template', payload)
    result.value = JSON.stringify(data, null, 2)
  } catch (e:any) {
    result.value = String(e?.message || e)
  }
}
</script>
