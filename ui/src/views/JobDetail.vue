<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Job: {{ jobId.slice(0,8) }}</h2>
      <router-link to="/jobs" class="btn btn-primary" style="text-decoration:none;">Back</router-link>
    </div>

    <Loading v-if="loading" />
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else-if="job">
      <div class="card">
        <div style="display:flex; gap:24px; flex-wrap:wrap; align-items:center;">
          <div><strong>{{ job.workflow_name }}</strong></div>
          <span class="badge" :class="'badge-'+job.status">{{ job.status }}</span>
          <span v-if="isDryRun" class="badge badge-pending">dry-run</span>
          <span style="font-size:12px; color:var(--color-text-muted);">triggered by {{ job.triggered_by || '—' }}</span>
          <span style="font-size:12px; color:var(--color-text-muted);">
            {{ job.duration_seconds != null ? job.duration_seconds.toFixed(1)+'s' : '—' }}
            <span v-if="job.timeout"> / timeout {{ job.timeout }}s</span>
          </span>
        </div>
        <div style="margin-top:8px; font-size:12px; color:var(--color-text-faint);">
          <span>triggered: {{ fmt(job.triggered_at) }}</span>
          <span v-if="job.started_at"> · started: {{ fmt(job.started_at) }}</span>
          <span v-if="job.finished_at"> · finished: {{ fmt(job.finished_at) }}</span>
        </div>
        <router-link v-if="canReadAudit" class="btn" style="margin-top:8px; text-decoration:none; display:inline-block;"
                     :to="{ path: '/audit-log', query: { resource_type: 'job', resource_id: jobId } }">Audit</router-link>
      </div>

      <div class="card" style="margin-top:12px;">
        <h2>Result</h2>
        <div v-if="job.result_success !== null" style="margin-bottom:8px;">
          <span v-if="job.result_success" class="badge badge-completed">success</span>
          <span v-else class="badge badge-failed">failure</span>
        </div>
        <div v-if="job.result_error" data-test="traceback">
          <div style="color:var(--color-result-fail); font-size:12px; margin-bottom:4px;">Error / traceback</div>
          <pre style="border:2px solid var(--color-danger);">{{ job.result_error }}</pre>
        </div>
        <div v-if="job.result_data" data-test="result-data">
          <div style="color:var(--color-text-muted); font-size:12px; margin-bottom:4px;">Result data</div>
          <pre>{{ JSON.stringify(job.result_data, null, 2) }}</pre>
        </div>
        <div v-if="!job.result_error && !job.result_data" class="empty">No result yet</div>
      </div>

      <div v-if="job.context && Object.keys(job.context).length" class="card" style="margin-top:12px;">
        <h2 style="cursor:pointer;" @click="contextOpen = !contextOpen">
          Context {{ contextOpen ? '▾' : '▸' }}
        </h2>
        <pre v-if="contextOpen" data-test="context">{{ JSON.stringify(job.context, null, 2) }}</pre>
      </div>

      <div v-if="canReadLogs" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <h2>Log</h2>
          <router-link :to="'/logs/'+jobId" class="btn" style="text-decoration:none;">Open full screen</router-link>
        </div>
        <div v-if="logError" class="error">{{ logError }}</div>
        <pre v-else data-test="log">{{ log || '(empty)' }}</pre>
      </div>
      <div v-else class="card" style="margin-top:12px;">
        <h2>Log</h2>
        <div class="empty">Роль "{{ auth.role }}" не имеет доступа к логам джобов</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api.js'
import { auth } from '../store/auth.js'
import { can } from '../permissions.js'
import Loading from '../components/Loading.vue'

const route = useRoute()
const jobId = route.params.id

const job = ref(null)
const log = ref('')
const logError = ref(null)
const loading = ref(true)
const error = ref(null)
const contextOpen = ref(false)
let timer = null

const canReadLogs = computed(() => can(auth.role, 'logs.read'))
const canReadAudit = computed(() => can(auth.role, 'audit.read'))
const isDryRun = computed(() => !!(job.value && job.value.context && job.value.context.dry_run))

function fmt(iso) {
  return iso ? new Date(iso).toLocaleString() : '—'
}

function isTerminal(status) {
  return status !== 'pending' && status !== 'running'
}

async function loadLog() {
  if (!canReadLogs.value) return
  try {
    log.value = await api.getLogs(jobId)
    logError.value = null
  } catch (e) {
    logError.value = e.message
  }
}

async function load() {
  try {
    job.value = await api.getJob(jobId)
    error.value = null
  } catch (e) {
    error.value = e.message
  }
  loading.value = false
  await loadLog()
}

function scheduleNext() {
  if (job.value && !isTerminal(job.value.status)) {
    timer = setTimeout(tick, 2000)
  }
}

async function tick() {
  await load()
  scheduleNext()
}

onMounted(async () => {
  await load()
  scheduleNext()
})

onUnmounted(() => {
  if (timer) clearTimeout(timer)
})
</script>
