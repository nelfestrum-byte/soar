<template>
  <div>
    <h2 style="margin-bottom:12px;">Workflows</h2>
    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <table>
        <tr><th>Name</th><th>Type</th><th>Schedule</th><th>Concurrency</th><th>Actions</th></tr>
        <tr v-for="wf in workflows" :key="wf.name">
          <td><strong>{{ wf.name }}</strong></td>
          <td><span class="badge" :class="'badge-'+wf.type">{{ wf.type }}</span></td>
          <td>{{ wf.schedule || wf.interval || '—' }}</td>
          <td>{{ wf.concurrency }}</td>
          <td>
            <button v-if="wf.enabled" class="btn btn-danger" @click="toggle(wf, false)">Disable</button>
            <button v-else class="btn btn-success" @click="toggle(wf, true)">Enable</button>
          </td>
        </tr>
      </table>
    </div>

    <div class="card" style="margin-top:16px;">
      <h2>Run Workflow</h2>
      <div style="display:flex; gap:8px; margin-top:8px;">
        <select v-model="selected">
          <option value="">Select workflow...</option>
          <option v-for="wf in workflows" :key="wf.name" :value="wf.name">{{ wf.name }}</option>
        </select>
        <button class="btn btn-primary" :disabled="!selected || running" @click="runJob">
          {{ running ? 'Running...' : 'Run' }}
        </button>
      </div>
      <div v-if="runResult" style="margin-top:8px; font-size:13px;">
        <span v-if="runResult.success" style="color:#2e7d32;">Job created: {{ runResult.job_id }}</span>
        <span v-else style="color:#c62828;">Error: {{ runResult.error }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const workflows = ref([])
const loading = ref(true)
const error = ref(null)
const selected = ref('')
const running = ref(false)
const runResult = ref(null)

async function load() {
  try { workflows.value = await api.getWorkflows() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function toggle(wf, enable) {
  try {
    if (enable) await api.enableWorkflow(wf.name)
    else await api.disableWorkflow(wf.name)
    wf.enabled = enable
  } catch (e) { alert(e.message) }
}

async function runJob() {
  if (!selected.value) return
  running.value = true
  runResult.value = null
  try {
    const res = await api.createJob(selected.value)
    runResult.value = { success: true, job_id: res.id }
  } catch (e) {
    runResult.value = { success: false, error: e.message }
  }
  running.value = false
}

onMounted(load)
</script>
