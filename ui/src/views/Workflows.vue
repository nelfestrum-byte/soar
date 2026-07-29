<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Workflows</h2>
      <button v-if="canWrite" class="btn btn-primary" @click="showNew = true">New Workflow</button>
    </div>

    <div v-if="showNew" class="card" style="margin-bottom:12px;">
      <h2>New Workflow</h2>
      <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
        <input v-model="newName" placeholder="MyWorkflow" style="flex:1; min-width:150px;" />
        <select v-model="newType">
          <option value="scheduled">Scheduled</option>
          <option value="webhook">Webhook</option>
          <option value="manual">Manual</option>
        </select>
        <button class="btn btn-primary" @click="createWorkflow" :disabled="!newName || creating">
          {{ creating ? 'Creating...' : 'Create' }}
        </button>
        <button class="btn" @click="showNew = false">Cancel</button>
      </div>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card">
        <table>
          <tr><th></th><th>Name</th><th>Type</th><th>Status</th><th>Actions</th></tr>
          <template v-for="wf in fileWorkflows" :key="wf.name">
            <tr>
              <td style="cursor:pointer; width:16px;" @click="toggleDetail(wf.name)">{{ isOpen(wf.name) ? '▾' : '▸' }}</td>
              <td style="font-family:monospace; cursor:pointer;" @click="toggleDetail(wf.name)">{{ wf.name }}.py</td>
              <td><span class="badge" :class="'badge-'+wf.type">{{ wf.type }}</span></td>
              <td>
                <template v-if="wf.meta">
                  <span v-if="wf.meta.enabled" class="badge badge-completed">enabled</span>
                  <span v-else class="badge badge-cancelled">disabled</span>
                </template>
                <span v-else class="loading">—</span>
              </td>
              <td style="white-space:nowrap;">
                <template v-if="wf.meta && canToggle">
                  <button v-if="wf.meta.enabled" class="btn btn-danger" style="font-size:11px;" @click="toggle(wf.className, false)">Disable</button>
                  <button v-else class="btn btn-success" style="font-size:11px;" @click="toggle(wf.className, true)">Enable</button>
                </template>
                <button class="btn btn-primary" style="font-size:11px;" @click="editWorkflow(wf.name)">{{ canWrite ? 'Edit' : 'View' }}</button>
                <button v-if="wf.type === 'manual' && canRun" class="btn btn-success" style="font-size:11px;" @click="showRun(wf.className)">Run</button>
                <router-link class="btn" style="font-size:11px; text-decoration:none;" :to="{ path: '/jobs', query: { workflow_name: wf.name } }">Jobs</router-link>
                <router-link v-if="can(auth.role, 'audit.read')" class="btn" style="font-size:11px; text-decoration:none;"
                             :to="{ path: '/audit-log', query: { resource_type: 'workflow', resource_id: wf.name } }">Audit</router-link>
                <button v-if="canWrite" class="btn btn-danger" style="font-size:11px;" @click="removeWorkflow(wf.name)">Delete</button>
              </td>
            </tr>
            <tr v-if="isOpen(wf.name)" data-test="detail-row">
              <td></td>
              <td colspan="4" style="background:#fafafa; font-size:13px;">
                <p v-if="wf.meta && wf.meta.docstring" style="white-space:pre-wrap; color:#555;">{{ wf.meta.docstring }}</p>
                <p v-else style="color:#999;">No docstring</p>

                <div v-if="wf.meta" style="display:flex; gap:16px; flex-wrap:wrap; color:#666; margin-bottom:8px;">
                  <span v-if="wf.meta.schedule">schedule: <code>{{ wf.meta.schedule }}</code></span>
                  <span v-if="wf.meta.interval">interval: {{ wf.meta.interval }}s</span>
                  <span v-if="wf.meta.timeout">timeout: {{ wf.meta.timeout }}s</span>
                  <span v-if="wf.meta.concurrency">concurrency: {{ wf.meta.concurrency }}</span>
                  <span v-if="nextRunFor(wf.name)">next run: {{ new Date(nextRunFor(wf.name)).toLocaleString() }}</span>
                </div>

                <div v-if="wf.type === 'webhook' && wf.meta && wf.meta.token">
                  <div style="display:flex; gap:8px; align-items:center; margin-bottom:4px;">
                    <code>{{ webhookUrl(location.origin, wf.name) }}</code>
                    <button class="btn" style="font-size:11px;" @click="copy(webhookUrl(location.origin, wf.name))">Copy URL</button>
                    <button class="btn" style="font-size:11px;" @click="tokenVisible[wf.name] = !tokenVisible[wf.name]">
                      {{ tokenVisible[wf.name] ? 'Hide token' : 'Show token' }}
                    </button>
                  </div>
                  <template v-if="tokenVisible[wf.name]">
                    <pre style="white-space:pre-wrap;">{{ webhookCurl(location.origin, wf.name, wf.meta.token) }}</pre>
                    <button class="btn" style="font-size:11px;" @click="copy(webhookCurl(location.origin, wf.name, wf.meta.token))">Copy curl</button>
                  </template>
                </div>
              </td>
            </tr>
          </template>
        </table>
      </div>

      <div v-if="editMode" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h2 style="margin:0;">{{ editName }}.py</h2>
          <div style="display:flex; gap:8px;">
            <button class="btn" :class="editTab==='code' ? 'btn-primary' : ''" @click="editTab='code'">Code</button>
            <button class="btn" :class="editTab==='history' ? 'btn-primary' : ''" @click="editTab='history'">History</button>
            <button v-if="canWrite && editTab==='code'" class="btn btn-primary" @click="saveWorkflow" :disabled="saving">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
            <button class="btn" @click="editMode = false">Close</button>
          </div>
        </div>
        <template v-if="editTab==='code'">
          <textarea v-model="content" :readonly="!canWrite" style="width:100%; min-height:400px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical; tab-size:4;"></textarea>
          <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
            <span v-if="saveResult.success" style="color:#2e7d32;">Saved (commit: {{ saveResult.commit }})</span>
            <span v-else style="color:#c62828;">Error: {{ saveResult.error }}</span>
          </div>
        </template>
        <HistoryPanel v-else entity="workflow" :name="editName" @restored="editWorkflow(editName)" />
      </div>

      <div v-if="runMode" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h2 style="margin:0;">Run: {{ runName }}</h2>
          <button class="btn" @click="runMode = false">Close</button>
        </div>
        <div style="margin-bottom:8px; font-size:13px; color:#666;">Payload (JSON):</div>
        <textarea v-model="payload" style="width:100%; min-height:150px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical; tab-size:4;"></textarea>
        <div style="margin-top:8px;">
          <button class="btn btn-success" @click="runJob" :disabled="running">
            {{ running ? 'Running...' : 'Run' }}
          </button>
        </div>
        <div v-if="runResult" style="margin-top:8px; font-size:13px;">
          <span v-if="runResult.success" style="color:#2e7d32;">Job created: {{ runResult.job_id }}</span>
          <span v-else style="color:#c62828;">Error: {{ runResult.error }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'
import { auth } from '../store/auth.js'
import { can } from '../permissions.js'
import { notify } from '../store/toast.js'
import HistoryPanel from '../components/HistoryPanel.vue'
import { webhookUrl, webhookCurl } from '../webhook.js'

const canWrite = computed(() => can(auth.role, 'code.write'))
const canToggle = computed(() => can(auth.role, 'workflow.toggle'))
const canRun = computed(() => can(auth.role, 'job.create'))

const location = window.location

const fileWorkflows = ref([])
const metaMap = ref({})
const loading = ref(true)
const error = ref(null)
const nextRuns = ref([])
const openNames = ref(new Set())
const tokenVisible = ref({})

function isOpen(name) {
  return openNames.value.has(name)
}

function toggleDetail(name) {
  const next = new Set(openNames.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  openNames.value = next
}

function nextRunFor(name) {
  const run = nextRuns.value.find((r) => r.workflow === name)
  return run ? run.at : null
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    notify.success('Copied')
  } catch {
    notify.error('Clipboard unavailable — copy manually')
  }
}

const editMode = ref(false)
const editTab = ref('code')
const editName = ref('')
const content = ref('')
const saving = ref(false)
const saveResult = ref(null)

const showNew = ref(false)
const newName = ref('')
const newType = ref('scheduled')
const creating = ref(false)

const runMode = ref(false)
const runName = ref('')
const payload = ref('{\n  \n}')
const running = ref(false)
const runResult = ref(null)

async function loadAll() {
  try {
    const workflows = await api.getWorkflows()
    const map = {}
    for (const wf of workflows) {
      map[wf.name] = wf
    }
    metaMap.value = map

    fileWorkflows.value = workflows.map(wf => ({
      name: wf.name,
      type: wf.type,
      className: wf.class_name || wf.name,
      meta: wf,
    }))
  } catch (e) { error.value = e.message }
  loading.value = false

  try {
    const status = await api.getStatus()
    nextRuns.value = status.scheduler.next_runs
  } catch {
    // scheduler panel is a nice-to-have here — Status.vue is the source of truth
  }
}

async function editWorkflow(name) {
  editName.value = name
  editMode.value = true
  editTab.value = 'code'
  saveResult.value = null
  try {
    const res = await api.getWorkflowCode(name)
    content.value = res.content
  } catch (e) { content.value = `Error: ${e.message}` }
}

async function saveWorkflow() {
  saving.value = true
  saveResult.value = null
  try {
    const res = await api.saveWorkflowCode(editName.value, content.value)
    saveResult.value = { success: true, commit: res.commit }
    await loadAll()
  } catch (e) {
    saveResult.value = { success: false, error: e.message }
  }
  saving.value = false
}

async function createWorkflow() {
  creating.value = true
  try {
    const res = await api.getWorkflowTemplate(newName.value, newType.value)
    await api.saveWorkflowCode(newName.value, res.content)
    await api.reloadWorkflows()
    showNew.value = false
    const created = newName.value
    newName.value = ''
    await loadAll()
    editWorkflow(created)
  } catch (e) { error.value = e.message }
  creating.value = false
}

async function removeWorkflow(name) {
  if (!confirm(`Delete workflow "${name}"?`)) return
  try {
    await api.deleteWorkflowCode(name)
    if (editName.value === name) editMode.value = false
    await loadAll()
  } catch (e) { error.value = e.message }
}

async function toggle(name, enable) {
  try {
    if (enable) await api.enableWorkflow(name)
    else await api.disableWorkflow(name)
    metaMap.value[name].enabled = enable
  } catch (e) { notify.error(e.message) }
}

function showRun(name) {
  const wf = fileWorkflows.value.find(f => f.name === name)
  runName.value = wf?.className || name
  runMode.value = true
  runResult.value = null
  payload.value = '{\n  \n}'
}

async function runJob() {
  running.value = true
  runResult.value = null
  let ctx = {}
  try {
    ctx = JSON.parse(payload.value)
  } catch (e) {
    runResult.value = { success: false, error: 'Invalid JSON' }
    running.value = false
    return
  }
  try {
    const res = await api.createJob(runName.value, ctx)
    runResult.value = { success: true, job_id: res.id }
    await loadAll()
  } catch (e) {
    runResult.value = { success: false, error: e.message }
  }
  running.value = false
}

onMounted(loadAll)
</script>
