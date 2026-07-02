<template>
  <div>
    <h2 style="margin-bottom:12px;">Generate Connector from OpenAPI Spec</h2>

    <div class="card">
      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:13px; font-weight:600; margin-bottom:4px;">Connector Name</label>
        <input v-model="connectorName" placeholder="my_api" style="width:300px;" />
      </div>

      <div style="margin-bottom:12px;">
        <label style="display:block; font-size:13px; font-weight:600; margin-bottom:4px;">OpenAPI Spec (JSON or YAML)</label>
        <textarea
          v-model="spec"
          placeholder="Paste your OpenAPI spec here..."
          style="width:100%; min-height:300px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical; tab-size:2;"
        ></textarea>
      </div>

      <div style="display:flex; gap:12px; margin-bottom:12px; flex-wrap:wrap; align-items:center;">
        <div>
          <label style="font-size:13px; font-weight:600;">Or upload file:</label>
          <input type="file" accept=".json,.yaml,.yml" @change="handleFileUpload" style="margin-left:8px;" />
        </div>
        <div style="display:flex; gap:8px; align-items:center;">
          <label style="font-size:13px; font-weight:600;">Or load from URL:</label>
          <input v-model="specUrl" placeholder="https://example.com/api.yaml" style="width:300px;" />
          <button class="btn btn-primary" @click="loadFromUrl" :disabled="!specUrl || loadingUrl">
            {{ loadingUrl ? 'Loading...' : 'Load' }}
          </button>
        </div>
      </div>

      <div style="display:flex; gap:8px;">
        <button class="btn btn-primary" @click="doPreview" :disabled="!spec || previewing">
          {{ previewing ? 'Previewing...' : 'Preview' }}
        </button>
        <button class="btn btn-success" @click="doGenerate" :disabled="!spec || !connectorName || generating">
          {{ generating ? 'Generating...' : 'Generate' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="error" style="margin-top:12px;">{{ error }}</div>

    <div v-if="preview" class="card" style="margin-top:12px;">
      <h2 style="margin-bottom:8px;">Preview</h2>
      <div style="font-size:13px; margin-bottom:8px;">
        <strong>{{ preview.title }}</strong> v{{ preview.version }}
      </div>
      <div v-if="preview.servers.length" style="font-size:13px; margin-bottom:8px; color:#666;">
        Server: {{ preview.servers[0] }}
      </div>
      <div v-if="preview.auth.length" style="font-size:13px; margin-bottom:8px; color:#666;">
        Auth: <span v-for="(a, i) in preview.auth" :key="i">{{ a.type }} ({{ a.name }})<span v-if="i < preview.auth.length - 1">, </span></span>
      </div>
      <table style="margin-top:8px;">
        <tr><th>Method</th><th>Path</th><th>Operation ID</th></tr>
        <tr v-for="(ep, i) in preview.endpoints" :key="i">
          <td><span class="badge" :class="methodBadge(ep.method)">{{ ep.method }}</span></td>
          <td style="font-family:monospace; font-size:12px;">{{ ep.path }}</td>
          <td style="font-size:12px; color:#666;">{{ ep.operationId || '—' }}</td>
        </tr>
      </table>
    </div>

    <div v-if="result" class="card" style="margin-top:12px;">
      <h2 style="margin-bottom:8px; color:#2e7d32;">✓ Connector "{{ result.name }}" generated!</h2>
      <div style="font-size:13px; margin-bottom:8px;">Files created:</div>
      <ul style="font-size:13px; margin:0; padding-left:20px;">
        <li v-for="f in result.files" :key="f" style="font-family:monospace;">{{ f }}</li>
      </ul>
      <div v-if="result.warnings.length" style="margin-top:8px;">
        <div v-for="w in result.warnings" :key="w" style="color:#e65100; font-size:12px;">⚠ {{ w }}</div>
      </div>
      <router-link :to="'/connectors'" class="btn btn-primary" style="display:inline-block; margin-top:12px; text-decoration:none;">
        View Connectors →
      </router-link>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../api.js'

const spec = ref('')
const connectorName = ref('')
const specUrl = ref('')
const preview = ref(null)
const result = ref(null)
const error = ref(null)
const previewing = ref(false)
const generating = ref(false)
const loadingUrl = ref(false)

function methodBadge(method) {
  const map = { GET: 'badge-completed', POST: 'badge-running', PUT: 'badge-pending', DELETE: 'badge-failed', PATCH: 'badge-cancelled' }
  return map[method] || ''
}

function handleFileUpload(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (ev) => { spec.value = ev.target.result }
  reader.readAsText(file)
}

async function loadFromUrl() {
  loadingUrl.value = true
  error.value = null
  try {
    const data = await api.previewUrl(specUrl.value)
    const resp = await fetch(specUrl.value)
    spec.value = await resp.text()
    preview.value = data
  } catch (e) {
    error.value = e.message
  }
  loadingUrl.value = false
}

async function doPreview() {
  previewing.value = true
  error.value = null
  try {
    preview.value = await api.preview(spec.value)
  } catch (e) {
    error.value = e.message
  }
  previewing.value = false
}

async function doGenerate() {
  generating.value = true
  error.value = null
  result.value = null
  try {
    result.value = await api.generateConnector(spec.value, connectorName.value)
  } catch (e) {
    error.value = e.message
  }
  generating.value = false
}
</script>
