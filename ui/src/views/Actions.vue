<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Actions</h2>
      <button class="btn btn-primary" @click="showNew = true">New Action</button>
    </div>

    <div v-if="showNew" class="card" style="margin-bottom:12px;">
      <h2>New Action</h2>
      <div style="display:flex; gap:8px; margin-top:8px;">
        <input v-model="newName" placeholder="action_name" style="flex:1;" />
        <button class="btn btn-primary" @click="createAction" :disabled="!newName || creating">
          {{ creating ? 'Creating...' : 'Create' }}
        </button>
        <button class="btn" @click="showNew = false">Cancel</button>
      </div>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card">
        <div v-if="actions.length">
          <div v-for="name in actions" :key="name"
               style="display:flex; align-items:center; gap:8px; padding:8px; border-bottom:1px solid #eee;"
               :style="{background: selected===name ? '#e3f2fd' : ''}">
            <span style="flex:1; cursor:pointer; font-family:monospace;" @click="loadAction(name)">{{ name }}.py</span>
            <button class="btn btn-danger" style="font-size:11px;" @click="removeAction(name)">Delete</button>
          </div>
        </div>
        <div v-else class="loading">No actions yet</div>
      </div>

      <div v-if="selected" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h2 style="margin:0;">{{ selected }}.py</h2>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-primary" @click="saveAction" :disabled="saving">
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

const actions = ref([])
const loading = ref(true)
const error = ref(null)
const selected = ref('')
const content = ref('')
const saving = ref(false)
const saveResult = ref(null)
const showNew = ref(false)
const newName = ref('')
const creating = ref(false)

async function loadActions() {
  try { actions.value = await api.getActions() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function loadAction(name) {
  selected.value = name
  saveResult.value = null
  try {
    const res = await api.getAction(name)
    content.value = res.content
  } catch (e) { content.value = `Error: ${e.message}` }
}

async function saveAction() {
  saving.value = true
  saveResult.value = null
  try {
    const res = await api.saveAction(selected.value, content.value)
    saveResult.value = { success: true, commit: res.commit }
  } catch (e) {
    saveResult.value = { success: false, error: e.message }
  }
  saving.value = false
}

async function createAction() {
  creating.value = true
  try {
    const res = await api.getActionTemplate(newName.value)
    await api.saveAction(newName.value, res.content)
    showNew.value = false
    const created = newName.value
    newName.value = ''
    await loadActions()
    selected.value = created
    await loadAction(created)
  } catch (e) {
    error.value = e.message
  }
  creating.value = false
}

async function removeAction(name) {
  if (!confirm(`Delete action "${name}"?`)) return
  try {
    await api.deleteAction(name)
    if (selected.value === name) { selected.value = ''; content.value = '' }
    await loadActions()
  } catch (e) { error.value = e.message }
}

onMounted(loadActions)
</script>
