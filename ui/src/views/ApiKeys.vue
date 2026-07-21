<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">API Keys</h2>
      <button class="btn btn-primary" @click="showNew = true">New Key</button>
    </div>

    <div v-if="showNew" class="card" style="margin-bottom:12px;">
      <h2>New API Key</h2>
      <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
        <input v-model="newName" placeholder="key name" style="flex:1; min-width:150px;" />
        <select v-model="newRole">
          <option value="service">service</option>
          <option value="viewer">viewer</option>
          <option value="analyst">analyst</option>
          <option value="admin">admin</option>
        </select>
        <button class="btn btn-primary" @click="createKey" :disabled="!newName || creating">
          {{ creating ? 'Creating...' : 'Create' }}
        </button>
        <button class="btn" @click="showNew = false">Cancel</button>
      </div>
    </div>

    <div v-if="created" class="card" style="margin-bottom:12px; background:#e8f5e9;">
      <h2>Key created — copy it now, it won't be shown again</h2>
      <pre>{{ created.key }}</pre>
      <button class="btn" @click="created = null">Dismiss</button>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <table v-if="keys.length">
        <tr><th>Name</th><th>Prefix</th><th>Role</th><th>Active</th><th>Last used</th><th>Expires</th><th></th></tr>
        <tr v-for="k in keys" :key="k.id">
          <td>{{ k.name }}</td>
          <td style="font-family:monospace;">{{ k.key_prefix }}…</td>
          <td>{{ k.role }}</td>
          <td>
            <span class="badge" :class="k.is_active ? 'badge-completed' : 'badge-cancelled'">
              {{ k.is_active ? 'active' : 'inactive' }}
            </span>
          </td>
          <td>{{ k.last_used_at ? new Date(k.last_used_at).toLocaleString() : '—' }}</td>
          <td>{{ k.expires_at ? new Date(k.expires_at).toLocaleString() : '—' }}</td>
          <td>
            <router-link class="btn" style="font-size:11px; text-decoration:none;"
                         :to="{ path: '/audit-log', query: { resource_type: 'apikey', resource_id: String(k.id) } }">Audit</router-link>
            <button class="btn btn-danger" style="font-size:11px;" @click="removeKey(k.id)">Delete</button>
          </td>
        </tr>
      </table>
      <div v-else class="loading">No API keys yet</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

const keys = ref([])
const loading = ref(true)
const error = ref(null)
const showNew = ref(false)
const newName = ref('')
const newRole = ref('service')
const creating = ref(false)
const created = ref(null)

async function loadKeys() {
  loading.value = true
  try { keys.value = await api.listApiKeys() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function createKey() {
  creating.value = true
  try {
    created.value = await api.createApiKey(newName.value, newRole.value)
    showNew.value = false
    newName.value = ''
    await loadKeys()
  } catch (e) {
    error.value = e.message
  }
  creating.value = false
}

async function removeKey(id) {
  if (!confirm('Delete this API key?')) return
  try {
    await api.deleteApiKey(id)
    await loadKeys()
  } catch (e) { error.value = e.message }
}

onMounted(loadKeys)
</script>
