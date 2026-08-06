<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Actions</h2>
      <button v-if="canWrite" class="btn btn-primary" @click="showNew = true">New Action</button>
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

    <Loading v-if="loading" />
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card">
        <div v-if="actions.length">
          <div v-for="action in actions" :key="action.name"
               style="display:flex; align-items:center; gap:8px; padding:8px; border-bottom:1px solid var(--color-border-subtle);"
               :style="{background: selected===action.name ? 'var(--status-running-bg)' : ''}">
            <span style="flex:1; cursor:pointer;" @click="loadAction(action.name)">
              <span style="font-family:var(--font-mono);">{{ action.name }}.py</span>
              <span v-if="action.summary" style="color:var(--color-text-faint); font-size:12px; margin-left:8px;">{{ action.summary }}</span>
            </span>
            <RowMenu>
              <router-link v-if="can(auth.role, 'audit.read')" class="btn"
                           :to="{ path: '/audit-log', query: { resource_type: 'action', resource_id: action.name } }">Audit</router-link>
              <button v-if="canWrite" class="btn row-menu-item-danger" @click="removeAction(action.name)">Delete</button>
            </RowMenu>
          </div>
        </div>
        <div v-else class="empty">No actions yet</div>
      </div>

      <div v-if="selected" class="card" style="margin-top:12px;">
        <h2 style="margin:0 0 8px;">{{ selected }}.py</h2>
        <div class="editor-toolbar">
          <button class="btn" :class="editTab==='code' ? 'btn-primary' : ''" @click="editTab='code'">Code</button>
          <button class="btn" :class="editTab==='signature' ? 'btn-primary' : ''" @click="showSignature">Signature</button>
          <button class="btn" :class="editTab==='history' ? 'btn-primary' : ''" @click="editTab='history'">History</button>
          <button v-if="canWrite && editTab==='code'" class="btn btn-primary" @click="saveAction" :disabled="saving">
            {{ saving ? 'Saving...' : 'Save' }}
          </button>
        </div>
        <template v-if="editTab==='code'">
          <CodeEditor v-model="content" language="python" height="400px" :readOnly="!canWrite" />
          <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
            <span v-if="saveResult.success" style="color:var(--color-result-ok);">Saved (commit: {{ saveResult.commit }})</span>
            <span v-else style="color:var(--color-result-fail);">Error: {{ saveResult.error }}</span>
          </div>
        </template>
        <template v-else-if="editTab==='signature'">
          <div v-if="signatureError" class="error">{{ signatureError }}</div>
          <template v-else-if="signature">
            <p style="font-family:var(--font-mono); font-size:13px;">{{ signature.name }}{{ signature.signature }}</p>
            <p v-if="signature.docstring" style="color:var(--color-text-muted); white-space:pre-wrap;">{{ signature.docstring }}</p>
            <p v-else class="empty">No docstring</p>
          </template>
        </template>
        <HistoryPanel v-else entity="action" :name="selected" @restored="loadAction(selected)" />
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
import CodeEditor from '../components/CodeEditor.vue'

const canWrite = computed(() => can(auth.role, 'code.write'))

const actions = ref([])
const loading = ref(true)
const error = ref(null)
const selected = ref('')
const editTab = ref('code')
const content = ref('')
const saving = ref(false)
const saveResult = ref(null)
const showNew = ref(false)
const newName = ref('')
const creating = ref(false)
const signature = ref(null)
const signatureError = ref(null)

async function showSignature() {
  editTab.value = 'signature'
  signature.value = null
  signatureError.value = null
  try { signature.value = await api.getActionDescribe(selected.value) }
  catch (e) { signatureError.value = e.message }
}

async function loadActions() {
  try { actions.value = await api.getActions() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function loadAction(name) {
  selected.value = name
  saveResult.value = null
  editTab.value = 'code'
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
