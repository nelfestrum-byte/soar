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
        <tr><th>ID</th><th>Workflow</th><th>Triggered</th><th>Status</th><th>Result</th><th>Duration</th><th>Actions</th></tr>
        <tr v-for="job in jobs" :key="job.id" class="job-row" @click="openDetail(job)">
          <td style="font-family:monospace; font-size:11px;">{{ job.id.slice(0,8) }}</td>
          <td>{{ job.workflow_name }}</td>
          <td>{{ job.triggered_by }}</td>
          <td>
            <span class="badge" :class="'badge-'+job.status">{{ job.status }}</span>
            <span v-if="job.context && job.context.dry_run" class="badge badge-pending" style="margin-left:4px;">dry-run</span>
          </td>
          <td style="max-width:260px;">
            <span v-if="job.result_success === true" style="color:#2e7d32;">&#10003;</span>
            <span v-else-if="job.result_success === false" style="color:#c62828;">
              &#10007; <span style="font-size:11px;">{{ firstLine(job.result_error) }}</span>
            </span>
            <span v-else>—</span>
          </td>
          <td>{{ job.duration_seconds ? job.duration_seconds.toFixed(1)+'s' : '—' }}</td>
          <td @click.stop>
            <router-link v-if="job.log_path && canReadLogs" :to="'/logs/'+job.id" class="btn btn-primary" style="text-decoration:none;">Log</router-link>
            <button v-else-if="job.log_path" class="btn" disabled
                    :title="`Роль ${auth.role} не имеет доступа к логам джобов`">Log</button>
            <router-link v-if="can(auth.role, 'audit.read')" class="btn" style="text-decoration:none;"
                         :to="{ path: '/audit-log', query: { resource_type: 'job', resource_id: job.id } }">Audit</router-link>
            <button v-if="canCancel && (job.status==='pending'||job.status==='running')" class="btn btn-danger" @click="cancel(job)">Cancel</button>
          </td>
        </tr>
      </table>
      <div v-if="!jobs.length" class="loading">No jobs found</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { auth } from '../store/auth.js'
import { can } from '../permissions.js'
import { notify } from '../store/toast.js'

const route = useRoute()
const router = useRouter()

const canReadLogs = computed(() => can(auth.role, 'logs.read'))
const canCancel = computed(() => can(auth.role, 'job.cancel'))

const jobs = ref([])
const loading = ref(true)
const error = ref(null)
const filters = ref({
  workflow_name: route.query.workflow_name || '',
  status: route.query.status || '',
})
let timer = null

function openDetail(job) {
  router.push(`/jobs/${job.id}`)
}

function firstLine(text) {
  if (!text) return ''
  const line = text.split('\n')[0]
  return line.length > 80 ? line.slice(0, 80) + '…' : line
}

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
  catch (e) { notify.error(e.message) }
}

onMounted(() => { load(); timer = setInterval(load, 5000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.job-row { cursor: pointer; }
.job-row:hover { background: #f5f7fa; }
</style>
