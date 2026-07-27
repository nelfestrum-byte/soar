<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Connectors</h2>
      <button class="btn btn-primary" @click="showNew = true">New Connector</button>
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

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card">
        <table>
          <tr><th>Name</th><th>Class</th><th>Config</th><th>Actions</th></tr>
          <tr v-for="c in connectors" :key="c.name">
            <td style="font-family:monospace;">{{ c.name }}</td>
            <td style="font-size:12px; color:#666;">{{ c.class_name || '—' }}</td>
            <td>
              <span v-if="c.has_config" class="badge badge-completed">.yml</span>
              <span v-else class="badge badge-cancelled">none</span>
            </td>
            <td style="white-space:nowrap;">
              <button class="btn btn-primary" style="font-size:11px;" @click="editCode(c.name)">Edit</button>
              <button class="btn btn-success" style="font-size:11px;" @click="editConfig(c.name)">Setup</button>
              <router-link v-if="auth.role === 'admin'" class="btn" style="font-size:11px; text-decoration:none;"
                           :to="{ path: '/audit-log', query: { resource_type: 'connector', resource_id: c.name } }">Audit</router-link>
              <button class="btn btn-danger" style="font-size:11px;" @click="removeConnector(c.name)">Delete</button>
            </td>
          </tr>
        </table>
      </div>

      <div v-if="editMode" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h2 style="margin:0;">{{ editName }}.py</h2>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-primary" @click="saveCode" :disabled="saving">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
            <button class="btn" @click="editMode = false">Close</button>
          </div>
        </div>
        <textarea v-model="codeContent" style="width:100%; min-height:400px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical; tab-size:4;"></textarea>
        <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
          <span v-if="saveResult.success" style="color:#2e7d32;">Saved (commit: {{ saveResult.commit }})</span>
          <span v-else style="color:#c62828;">Error: {{ saveResult.error }}</span>
        </div>
      </div>

      <div v-if="configMode" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h2 style="margin:0;">{{ configName }}.yml</h2>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-primary" @click="saveConfig" :disabled="saving">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
            <button class="btn" @click="configMode = false">Close</button>
          </div>
        </div>

        <template v-if="!rawConfigMode">
          <div style="margin-bottom:8px;">
            <label style="font-size:12px; color:#666;">Instance ID</label><br />
            <input v-model="instanceId" style="width:100%;" />
          </div>
          <div v-for="f in visibleSchemaFields" :key="f.name" style="margin-bottom:8px;">
            <label style="font-size:12px; color:#666;">
              {{ f.name }} <span style="opacity:0.6;">({{ f.type }})</span>
              <span v-if="f.hidden" style="color:#c62828;"> — только admin может менять credentials</span>
            </label><br />
            <input v-if="f.type === 'bool'" type="checkbox" v-model="instanceValues[f.name]"
                   :disabled="f.hidden && auth.role !== 'admin'" />
            <input v-else-if="f.hidden" type="password" v-model="instanceValues[f.name]"
                   placeholder="оставьте пустым, чтобы не менять" :disabled="auth.role !== 'admin'"
                   style="width:100%;" />
            <input v-else :type="f.type === 'int' || f.type === 'float' ? 'number' : 'text'"
                   v-model="instanceValues[f.name]" style="width:100%;" />
          </div>
        </template>
        <textarea v-else v-model="configContent" style="width:100%; min-height:200px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical; tab-size:4;"></textarea>

        <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
          <span v-if="saveResult.success" style="color:#2e7d32;">Saved (commit: {{ saveResult.commit }})</span>
          <span v-else style="color:#c62828;">Error: {{ saveResult.error }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'
import { auth } from '../store/auth.js'

const connectors = ref([])
const loading = ref(true)
const error = ref(null)

const showNew = ref(false)
const newName = ref('')
const creating = ref(false)

const editMode = ref(false)
const editName = ref('')
const codeContent = ref('')

const configMode = ref(false)
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
