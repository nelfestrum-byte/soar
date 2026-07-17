<template>
  <div>
    <h2 style="margin-bottom:12px;">Tools</h2>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card">
        <div v-if="tools.length">
          <div v-for="t in tools" :key="t.module + '.' + t.name"
               style="display:flex; align-items:center; gap:12px; padding:8px; border-bottom:1px solid #eee; cursor:pointer;"
               :style="{background: selected === t.name ? '#e3f2fd' : ''}"
               @click="loadTool(t.name)">
            <span style="font-family:monospace; font-weight:600;">{{ t.name }}</span>
            <span style="color:#999; font-size:12px; font-family:monospace;">{{ t.module }}.py</span>
            <span style="flex:1; color:#666; font-size:12px;">{{ t.summary }}</span>
          </div>
        </div>
        <div v-else class="loading">No tools found</div>
      </div>

      <div v-if="detailError" class="error" style="margin-top:12px;">{{ detailError }}</div>

      <div v-if="detail" class="card" style="margin-top:12px;">
        <h2 style="margin:0 0 4px;">
          {{ detail.name }}
          <span style="color:#999; font-weight:400; font-size:13px;">{{ detail.module }}.py</span>
        </h2>
        <p v-if="detail.docstring" style="color:#555; margin:8px 0; white-space:pre-wrap;">{{ detail.docstring }}</p>
        <p style="font-family:monospace; font-size:13px; color:#666;">{{ detail.name }}{{ detail.constructor }}</p>

        <table style="margin-top:12px;">
          <tr><th>Method</th><th>Signature</th><th>Description</th></tr>
          <tr v-for="m in detail.methods" :key="m.name">
            <td style="font-family:monospace;">{{ m.name }}</td>
            <td style="font-family:monospace;">{{ m.signature }}</td>
            <td>{{ m.docstring.split('\n')[0] }}</td>
          </tr>
        </table>
        <div v-if="!detail.methods.length" class="loading">No public methods</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const tools = ref([])
const loading = ref(true)
const error = ref(null)
const selected = ref('')
const detail = ref(null)
const detailError = ref(null)

async function loadTools() {
  try { tools.value = await api.getTools() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function loadTool(name) {
  selected.value = name
  detail.value = null
  detailError.value = null
  try { detail.value = await api.getTool(name) }
  catch (e) { detailError.value = e.message }
}

onMounted(loadTools)
</script>
