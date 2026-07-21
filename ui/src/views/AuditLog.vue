<template>
  <div>
    <h2 style="margin-bottom:12px;">Audit Log</h2>
    <div class="card" style="margin-bottom:12px;">
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <select v-model="filters.resource_type">
          <option value="">All resource types</option>
          <option v-for="t in resourceTypes" :key="t" :value="t">{{ t }}</option>
        </select>
        <input v-model="filters.resource_id" placeholder="resource id (e.g. workflow name)" style="min-width:200px;" />
        <input v-model="filters.action" placeholder="action (e.g. workflow.update)" style="min-width:180px;" />
        <input v-model="filters.actor_name" placeholder="actor" style="min-width:120px;" />
        <button class="btn btn-primary" @click="reload">Filter</button>
        <button class="btn" @click="clearFilters" :disabled="!hasFilters">Clear</button>
      </div>
      <div v-if="hasFilters" style="margin-top:8px; font-size:12px; color:#666;">
        Showing only matching rows — clear filters to see the full audit log across all resources.
      </div>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <table>
        <tr><th>Time</th><th>Actor</th><th>Action</th><th>Resource</th><th>IP</th><th>Detail</th></tr>
        <tr v-for="row in rows" :key="row.id">
          <td style="white-space:nowrap; font-size:12px;">{{ new Date(row.created_at).toLocaleString() }}</td>
          <td>{{ row.actor_name }} <span style="color:#999; font-size:11px;">({{ row.actor_type }})</span></td>
          <td><span class="badge badge-running">{{ row.action }}</span></td>
          <td>
            <a href="#" style="text-decoration:none;" @click.prevent="filterByResource(row.resource_type, row.resource_id)">
              {{ row.resource_type }}/{{ row.resource_id }}
            </a>
          </td>
          <td style="font-family:monospace; font-size:11px;">{{ row.client_ip || '—' }}</td>
          <td style="font-family:monospace; font-size:11px;">{{ row.detail ? JSON.stringify(row.detail) : '—' }}</td>
        </tr>
      </table>
      <div v-if="!rows.length" class="loading">No audit entries found</div>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:12px;">
        <button class="btn" @click="prevPage" :disabled="offset === 0">Previous</button>
        <span style="font-size:12px; color:#666;">Rows {{ offset + 1 }}–{{ offset + rows.length }}</span>
        <button class="btn" @click="nextPage" :disabled="rows.length < limit">Next</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const router = useRouter()

const resourceTypes = ['workflow', 'action', 'connector', 'apikey', 'job']

const rows = ref([])
const loading = ref(true)
const error = ref(null)
const limit = ref(50)
const offset = ref(0)
const filters = ref({
  resource_type: route.query.resource_type || '',
  resource_id: route.query.resource_id || '',
  action: route.query.action || '',
  actor_name: route.query.actor_name || '',
})

const hasFilters = computed(() =>
  !!(filters.value.resource_type || filters.value.resource_id || filters.value.action || filters.value.actor_name)
)

async function load() {
  loading.value = true
  try {
    const params = { limit: limit.value, offset: offset.value }
    if (filters.value.resource_type) params.resource_type = filters.value.resource_type
    if (filters.value.resource_id) params.resource_id = filters.value.resource_id
    if (filters.value.action) params.action = filters.value.action
    if (filters.value.actor_name) params.actor_name = filters.value.actor_name
    rows.value = await api.getAuditLog(params)
    error.value = null
  } catch (e) { error.value = e.message }
  loading.value = false
}

function reload() {
  offset.value = 0
  load()
}

function clearFilters() {
  filters.value = { resource_type: '', resource_id: '', action: '', actor_name: '' }
  reload()
}

function filterByResource(resourceType, resourceId) {
  filters.value = { resource_type: resourceType, resource_id: resourceId, action: '', actor_name: '' }
  reload()
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit.value)
  load()
}

function nextPage() {
  offset.value += limit.value
  load()
}

onMounted(() => {
  load()
  // Reflect the initial resource_type/resource_id filter (from a deep link) in the URL
  // without keeping it in sync afterward — this is a landing filter, not shared state.
  if (route.query.resource_type || route.query.resource_id) {
    router.replace({ query: {} })
  }
})
</script>
