<template>
  <div>
    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div style="display:grid; grid-template-columns: repeat(4,1fr); gap:12px; margin-bottom:16px;">
        <div class="card">
          <h2>Workers</h2>
          <div style="font-size:28px; font-weight:700;">{{ status.workers.total }}</div>
          <div style="color:#999; font-size:12px;">busy: {{ status.workers.busy }} / idle: {{ status.workers.idle }}</div>
        </div>
        <div class="card">
          <h2>Queue</h2>
          <div style="font-size:28px; font-weight:700;">{{ status.queue.pending }}</div>
          <div style="color:#999; font-size:12px;">backend: {{ status.queue.backend }}</div>
        </div>
        <div class="card">
          <h2>Running</h2>
          <div style="font-size:28px; font-weight:700;">{{ status.jobs.running }}</div>
        </div>
        <div class="card">
          <h2>Today</h2>
          <div style="font-size:13px;">
            <span style="color:#2e7d32;">&#10003; {{ status.jobs.completed_today }}</span> &nbsp;
            <span style="color:#c62828;">&#10007; {{ status.jobs.failed_today }}</span> &nbsp;
            <span style="color:#ad1457;">&#9202; {{ status.jobs.timeout_today }}</span>
          </div>
        </div>
      </div>

      <div class="card">
        <h2>Upcoming Scheduled Runs</h2>
        <table v-if="status.scheduler.next_runs.length">
          <tr><th>Workflow</th><th>Next Run</th></tr>
          <tr v-for="r in status.scheduler.next_runs" :key="r.at">
            <td>{{ r.workflow }}</td>
            <td>{{ new Date(r.at).toLocaleString() }}</td>
          </tr>
        </table>
        <div v-else class="loading">No scheduled runs</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api.js'

const status = ref(null)
const loading = ref(true)
const error = ref(null)
let timer = null

async function load() {
  try {
    status.value = await api.getStatus()
    error.value = null
  } catch (e) { error.value = e.message }
  loading.value = false
}

onMounted(() => { load(); timer = setInterval(load, 3000) })
onUnmounted(() => clearInterval(timer))
</script>
