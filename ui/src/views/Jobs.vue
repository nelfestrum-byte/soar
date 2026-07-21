<template>
  <div>
    <h2 style="margin-bottom:12px;">Jobs</h2>
    <div class="card" style="margin-bottom:12px;">
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <select v-model="filters.workflow_name">
          <option value="">All workflows</option>
          <option v-for="n in workflowNames" :key="n" :value="n">{{ n }}</option>
        </select>
        <select v-model="filters.status">
          <option value="">All statuses</option>
          <option v-for="s in ['pending','running','completed','failed','timeout','cancelled']" :key="s" :value="s">{{ s }}</option>
        </select>
        <button class="btn btn-primary" @click="load">Refresh</button>
      </div>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <table>
        <tr><th>ID</th><th>Workflow</th><th>Triggered</th><th>Status</th><th>Duration</th><th>Actions</th></tr>
        <tr v-for="job in jobs" :key="job.id">
          <td style="font-family:monospace; font-size:11px;">{{ job.id.slice(0,8) }}</td>
          <td>{{ job.workflow_name }}</td>
          <td>{{ job.triggered_by }}</td>
          <td><span class="badge" :class="'badge-'+job.status">{{ job.status }}</span></td>
          <td>{{ job.duration_seconds ? job.duration_seconds.toFixed(1)+'s' : '—' }}</td>
          <td>
            <router-link v-if="job.log_path" :to="'/logs/'+job.id" class="btn btn-primary" style="text-decoration:none;">Log</router-link>
            <router-link v-if="auth.role === 'admin'" class="btn" style="text-decoration:none;"
                         :to="{ path: '/audit-log', query: { resource_type: 'job', resource_id: job.id } }">Audit</router-link>
            <button v-if="job.status==='pending'||job.status==='running'" class="btn btn-danger" @click="cancel(job)">Cancel</button>
          </td>
        </tr>
      </table>
      <div v-if="!jobs.length" class="loading">No jobs found</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api.js'
import { auth } from '../store/auth.js'

const jobs = ref([])
const loading = ref(true)
const error = ref(null)
const filters = ref({ workflow_name: '', status: '' })
let timer = null

const workflowNames = computed(() => [...new Set(jobs.value.map(j => j.workflow_name))])

async function load() {
  try {
    const params = {}
    if (filters.value.workflow_name) params.workflow_name = filters.value.workflow_name
    if (filters.value.status) params.status = filters.value.status
    jobs.value = await api.getJobs(params)
    error.value = null
  } catch (e) { error.value = e.message }
  loading.value = false
}

async function cancel(job) {
  if (!confirm(`Cancel job ${job.id.slice(0,8)}?`)) return
  try { await api.cancelJob(job.id); load() }
  catch (e) { alert(e.message) }
}

onMounted(() => { load(); timer = setInterval(load, 5000) })
onUnmounted(() => clearInterval(timer))
</script>
