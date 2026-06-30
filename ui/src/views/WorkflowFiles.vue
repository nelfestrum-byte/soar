<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Workflow Files</h2>
      <button class="btn btn-primary" @click="showNew = true">New Workflow</button>
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
        <div v-if="workflows.length">
          <div v-for="wf in workflows" :key="wf.name"
               style="display:flex; align-items:center; gap:8px; padding:8px; border-bottom:1px solid #eee;"
               :style="{background: selected===wf.name ? '#e3f2fd' : ''}">
            <span style="flex:1; cursor:pointer; font-family:monospace;" @click="loadWorkflow(wf.name)">{{ wf.name }}.py</span>
            <button class="btn btn-danger" style="font-size:11px;" @click="removeWorkflow(wf.name)">Delete</button>
          </div>
        </div>
        <div v-else class="loading">No workflows yet</div>
      </div>

      <div v-if="selected" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h2 style="margin:0;">{{ selected }}.py</h2>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-primary" @click="saveWorkflow" :disabled="saving">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
          </div>
        </div>
        <textarea v-model="content" style="width:100%; min-height:400px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical; tab-size:4;"></textarea>
        <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
          <span v-if="saveResult.success" style="color:#2e7d32;">Saved (commit: {{ saveResult.commit }})</span>
          <span v-else style="color:#c62828;">Error: {{ saveResult.error }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const workflows = ref([])
const loading = ref(true)
const error = ref(null)
const selected = ref('')
const content = ref('')
const saving = ref(false)
const saveResult = ref(null)
const showNew = ref(false)
const newName = ref('')
const newType = ref('scheduled')
const creating = ref(false)

async function loadWorkflows() {
  try { workflows.value = await api.getWorkflows() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function loadWorkflow(name) {
  selected.value = name
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
    const res = await api.saveWorkflowCode(selected.value, content.value)
    saveResult.value = { success: true, commit: res.commit }
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
    showNew.value = false
    const created = newName.value
    newName.value = ''
    await loadWorkflows()
    selected.value = created
    await loadWorkflow(created)
  } catch (e) {
    error.value = e.message
  }
  creating.value = false
}

async function removeWorkflow(name) {
  if (!confirm(`Delete workflow "${name}"?`)) return
  try {
    await api.deleteWorkflowCode(name)
    if (selected.value === name) { selected.value = ''; content.value = '' }
    await loadWorkflows()
  } catch (e) { error.value = e.message }
}

onMounted(loadWorkflows)
</script>
