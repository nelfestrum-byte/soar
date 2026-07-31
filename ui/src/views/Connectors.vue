<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Connectors</h2>
      <button v-if="canManage" class="btn btn-primary" @click="showNew = true">New Connector</button>
    </div>

    <div v-if="showNew" class="card" style="margin-bottom:12px;">
      <h2>New Connector</h2>
      <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
        <input v-model="newName" placeholder="my_connector" style="flex:1; min-width:150px;" />
        <button class="btn btn-primary" @click="createConnector" :disabled="!newName || creating">
          {{ creating ? 'Creating...' : 'Create' }}
        </button>
        <button class="btn" @click="showNew = false">Cancel</button>
      </div>
    </div>

    <Loading v-if="loading" />
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card">
        <table>
          <tr><th>Name</th><th>Class</th><th>Config</th><th>Actions</th></tr>
          <tr v-for="c in connectors" :key="c.name">
            <td style="font-family:var(--font-mono);">{{ c.name }}</td>
            <td style="font-size:12px; color:var(--color-text-muted);">{{ c.class_name || '—' }}</td>
            <td>
              <span v-if="c.has_config" class="badge badge-completed">.yml</span>
              <span v-else class="badge badge-cancelled">none</span>
            </td>
            <td style="white-space:nowrap;">
              <button class="btn btn-primary" style="font-size:11px;" @click="editCode(c.name)">{{ canWriteCode ? 'Edit' : 'View' }}</button>
              <button class="btn btn-success" style="font-size:11px;" @click="editConfig(c.name)">Setup</button>
              <RowMenu>
                <router-link v-if="can(auth.role, 'audit.read')" class="btn"
                             :to="{ path: '/audit-log', query: { resource_type: 'connector', resource_id: c.name } }">Audit</router-link>
                <button v-if="canManage" class="btn row-menu-item-danger" @click="removeConnector(c.name)">Delete</button>
              </RowMenu>
            </td>
          </tr>
        </table>
      </div>

      <div v-if="editMode" class="card" style="margin-top:12px;">
        <h2 style="margin:0 0 8px;">{{ editName }}.py</h2>
        <div class="editor-toolbar">
          <button class="btn" :class="codeTab==='code' ? 'btn-primary' : ''" @click="codeTab='code'">Code</button>
          <button class="btn" :class="codeTab==='signature' ? 'btn-primary' : ''" @click="showSignature">Signature</button>
          <button class="btn" :class="codeTab==='history' ? 'btn-primary' : ''" @click="codeTab='history'">History</button>
          <button v-if="canWriteCode && codeTab==='code'" class="btn btn-primary" @click="saveCode" :disabled="saving">
            {{ saving ? 'Saving...' : 'Save' }}
          </button>
          <button class="btn" @click="editMode = false">Close</button>
        </div>
        <template v-if="codeTab==='code'">
          <textarea v-model="codeContent" :readonly="!canWriteCode" style="width:100%; min-height:400px; font-family:var(--font-mono); font-size:12px; padding:8px; border:1px solid var(--color-border); border-radius:4px; resize:vertical; tab-size:4;"></textarea>
          <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
            <span v-if="saveResult.success" style="color:var(--color-result-ok);">Saved (commit: {{ saveResult.commit }})</span>
            <span v-else style="color:var(--color-result-fail);">Error: {{ saveResult.error }}</span>
          </div>
        </template>
        <template v-else-if="codeTab==='signature'">
          <div v-if="signatureError" class="error">{{ signatureError }}</div>
          <template v-else-if="signature">
            <h2 style="margin:0 0 4px;">{{ signature.name }}<span style="color:var(--color-text-muted); font-family:var(--font-mono); font-weight:400;">{{ signature.constructor }}</span></h2>
            <p v-if="signature.docstring" style="color:var(--color-text-muted); white-space:pre-wrap;">{{ signature.docstring }}</p>
            <table style="margin-top:12px;">
              <tr><th>Method</th><th>Signature</th><th>Description</th></tr>
              <tr v-for="m in signature.methods" :key="m.name">
                <td style="font-family:var(--font-mono);">{{ m.name }}</td>
                <td style="font-family:var(--font-mono);">{{ m.signature }}</td>
                <td>{{ m.docstring.split('\n')[0] }}</td>
              </tr>
            </table>
            <div v-if="!signature.methods.length" class="empty">No public methods</div>
          </template>
        </template>
        <HistoryPanel v-else entity="connector_code" :name="editName" @restored="editCode(editName)" />
      </div>

      <div v-if="configMode" class="card" style="margin-top:12px;">
        <h2 style="margin:0 0 8px;">{{ configName }}.yml</h2>
        <div class="editor-toolbar">
          <button class="btn" :class="configTab==='config' ? 'btn-primary' : ''" @click="configTab='config'">Config</button>
          <button class="btn" :class="configTab==='history' ? 'btn-primary' : ''" @click="configTab='history'">History</button>
          <button v-if="canWriteConfig && configTab==='config'" class="btn btn-primary" @click="saveConfig" :disabled="saving">
            {{ saving ? 'Saving...' : 'Save' }}
          </button>
          <button class="btn" @click="configMode = false">Close</button>
        </div>

        <template v-if="configTab==='config'">
          <template v-if="!rawConfigMode">
            <div style="margin-bottom:8px;">
              <label style="font-size:12px; color:var(--color-text-muted);">Instance ID</label><br />
              <input v-model="instanceId" style="width:100%;" />
            </div>
            <div v-for="f in visibleSchemaFields" :key="f.name" style="margin-bottom:8px;">
              <label style="font-size:12px; color:var(--color-text-muted);">
                {{ f.name }} <span style="opacity:0.6;">({{ f.type }})</span>
                <span v-if="f.hidden" style="color:var(--color-result-fail);"> — только admin может менять credentials</span>
              </label><br />
              <input v-if="f.type === 'bool'" type="checkbox" v-model="instanceValues[f.name]"
                     :disabled="!canWriteConfig || (f.hidden && auth.role !== 'admin')" />
              <input v-else-if="f.hidden" type="password" v-model="instanceValues[f.name]"
                     placeholder="оставьте пустым, чтобы не менять" :disabled="auth.role !== 'admin'"
                     style="width:100%;" />
              <input v-else :type="f.type === 'int' || f.type === 'float' ? 'number' : 'text'"
                     v-model="instanceValues[f.name]" :disabled="!canWriteConfig" style="width:100%;" />
            </div>
          </template>
          <textarea v-else v-model="configContent" :readonly="!canWriteConfig" style="width:100%; min-height:200px; font-family:var(--font-mono); font-size:12px; padding:8px; border:1px solid var(--color-border); border-radius:4px; resize:vertical; tab-size:4;"></textarea>

          <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
            <span v-if="saveResult.success" style="color:var(--color-result-ok);">Saved (commit: {{ saveResult.commit }})</span>
            <span v-else style="color:var(--color-result-fail);">Error: {{ saveResult.error }}</span>
          </div>
        </template>
        <HistoryPanel v-else entity="connector_config" :name="configName" @restored="editConfig(configName)" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'
import { auth } from '../store/auth.js'
import { can } from '../permissions.js'
import HistoryPanel from '../components/HistoryPanel.vue'
import RowMenu from '../components/RowMenu.vue'
import Loading from '../components/Loading.vue'

const canManage = computed(() => can(auth.role, 'connector.manage'))
const canWriteCode = computed(() => can(auth.role, 'connector.code.write'))
const canWriteConfig = computed(() => can(auth.role, 'connector.config.write'))

const connectors = ref([])
const loading = ref(true)
const error = ref(null)

const showNew = ref(false)
const newName = ref('')
const creating = ref(false)

const editMode = ref(false)
const editName = ref('')
const codeContent = ref('')
const codeTab = ref('code')
const signature = ref(null)
const signatureError = ref(null)

async function showSignature() {
  codeTab.value = 'signature'
  signature.value = null
  signatureError.value = null
  try { signature.value = await api.getConnectorDescribe(editName.value) }
  catch (e) { signatureError.value = e.message }
}

const configMode = ref(false)
const configTab = ref('config')
const configName = ref('')
const configContent = ref('')
const schemaFields = ref([])
const rawConfigMode = ref(false)
const instanceId = ref('')
const instanceValues = ref({})

const visibleSchemaFields = computed(() => schemaFields.value.filter((f) => f.name !== 'instance_name'))

const saving = ref(false)
const saveResult = ref(null)

// Narrow parser for the `instances: {id: {key: value}}` shape saved by the
// backend (soar/connectors/*.yml) — not a general YAML parser.
function parseSimpleYamlInstances(text) {
  const result = {}
  let currentInstance = null
  let inInstances = false
  for (const raw of (text || '').split(/\r?\n/)) {
    const trimmed = raw.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const indent = raw.match(/^ */)[0].length
    if (!inInstances) {
      if (trimmed === 'instances:') inInstances = true
      continue
    }
    if (indent === 2 && trimmed.endsWith(':')) {
      currentInstance = trimmed.slice(0, -1).trim()
      result[currentInstance] = {}
      continue
    }
    if (indent >= 4 && currentInstance && trimmed.includes(':')) {
      const idx = trimmed.indexOf(':')
      const key = trimmed.slice(0, idx).trim()
      result[currentInstance][key] = unquoteYamlScalar(trimmed.slice(idx + 1).trim())
    }
  }
  return result
}

function unquoteYamlScalar(value) {
  if (value === '') return ''
  if ((value.startsWith("'") && value.endsWith("'")) || (value.startsWith('"') && value.endsWith('"'))) {
    return value.slice(1, -1)
  }
  if (value === 'true') return true
  if (value === 'false') return false
  if (value !== '' && !isNaN(Number(value))) return Number(value)
  return value
}

function yamlScalar(value) {
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') return String(value)
  return String(value)
}

function buildConfigYaml() {
  const id = instanceId.value || configName.value
  let out = `instances:\n  ${id}:\n`
  for (const f of visibleSchemaFields.value) {
    const value = instanceValues.value[f.name]
    if (value === '' || value === undefined || value === null) continue
    out += `    ${f.name}: ${yamlScalar(value)}\n`
  }
  return out
}

async function loadConnectors() {
  try { connectors.value = await api.getConnectors() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function editCode(name) {
  editName.value = name
  editMode.value = true
  configMode.value = false
  codeTab.value = 'code'
  saveResult.value = null
  try {
    const res = await api.getConnectorCode(name)
    codeContent.value = res.content
  } catch (e) { codeContent.value = `Error: ${e.message}` }
}

async function saveCode() {
  saving.value = true
  saveResult.value = null
  try {
    const res = await api.saveConnectorCode(editName.value, codeContent.value)
    saveResult.value = { success: true, commit: res.commit }
    await loadConnectors()
  } catch (e) {
    saveResult.value = { success: false, error: e.message }
  }
  saving.value = false
}

async function editConfig(name) {
  configName.value = name
  configMode.value = true
  editMode.value = false
  configTab.value = 'config'
  saveResult.value = null
  schemaFields.value = []
  rawConfigMode.value = false
  instanceId.value = ''
  instanceValues.value = {}
  try {
    const [configRes, schemaRes] = await Promise.all([
      api.getConnectorConfig(name),
      api.getConnectorSchema(name).catch(() => ({ fields: [] })),
    ])
    configContent.value = configRes.content
    schemaFields.value = schemaRes.fields || []
    if (schemaFields.value.length === 0) {
      rawConfigMode.value = true
      return
    }
    const parsed = parseSimpleYamlInstances(configContent.value)
    const ids = Object.keys(parsed)
    instanceId.value = ids[0] || name
    const existing = parsed[instanceId.value] || {}
    const values = {}
    for (const f of visibleSchemaFields.value) {
      if (f.hidden) { values[f.name] = ''; continue }
      values[f.name] = existing[f.name] !== undefined ? existing[f.name] : (f.default ?? '')
    }
    instanceValues.value = values
  } catch (e) {
    configContent.value = `Error: ${e.message}`
    rawConfigMode.value = true
  }
}

async function saveConfig() {
  saving.value = true
  saveResult.value = null
  try {
    const payload = rawConfigMode.value ? configContent.value : buildConfigYaml()
    const res = await api.saveConnectorConfig(configName.value, payload)
    saveResult.value = { success: true, commit: res.commit }
    await loadConnectors()
  } catch (e) {
    saveResult.value = { success: false, error: e.message }
  }
  saving.value = false
}

async function createConnector() {
  creating.value = true
  try {
    await api.createConnector(newName.value)
    showNew.value = false
    const created = newName.value
    newName.value = ''
    await loadConnectors()
    editCode(created)
  } catch (e) { error.value = e.message }
  creating.value = false
}

async function removeConnector(name) {
  if (!confirm(`Delete connector "${name}"?`)) return
  try {
    await api.deleteConnector(name)
    if (editName.value === name) editMode.value = false
    if (configName.value === name) configMode.value = false
    await loadConnectors()
  } catch (e) { error.value = e.message }
}

onMounted(loadConnectors)
</script>
