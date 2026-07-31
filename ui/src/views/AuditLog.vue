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
        <input v-model="filters.since" type="datetime-local" title="since" />
        <input v-model="filters.until" type="datetime-local" title="until" />
        <button class="btn btn-primary" @click="reload">Filter</button>
        <button class="btn" @click="clearFilters" :disabled="!hasFilters">Clear</button>
      </div>
      <div style="margin-top:8px; display:flex; gap:8px;">
        <button class="btn" style="font-size:11px;" @click="applyPreset('hour')">Last hour</button>
        <button class="btn" style="font-size:11px;" @click="applyPreset('day')">Last 24h</button>
        <button class="btn" style="font-size:11px;" @click="applyPreset('week')">Last week</button>
      </div>
      <div v-if="hasFilters" style="margin-top:8px; font-size:12px; color:var(--color-text-muted);">
        Showing only matching rows — clear filters to see the full audit log across all resources.
      </div>
    </div>

    <Loading v-if="loading" />
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <table>
        <tr><th>Time</th><th>Actor</th><th>Action</th><th>Resource</th><th>IP</th><th>Detail</th></tr>
        <tr v-for="row in rows" :key="row.id">
          <td style="white-space:nowrap; font-size:12px;">{{ new Date(row.created_at).toLocaleString() }}</td>
          <td>{{ row.actor_name }} <span style="color:var(--color-text-faint); font-size:11px;">({{ row.actor_type }})</span></td>
          <td><span class="badge badge-running">{{ row.action }}</span></td>
          <td>
            <a href="#" style="text-decoration:none;" @click.prevent="filterByResource(row.resource_type, row.resource_id)">
              {{ row.resource_type }}/{{ row.resource_id }}
            </a>
          </td>
          <td style="font-family:var(--font-mono); font-size:11px;">{{ row.client_ip || '—' }}</td>
          <td style="font-family:var(--font-mono); font-size:11px; max-width:280px;">
            <template v-if="row.detail">
              <span style="cursor:pointer; text-decoration:underline dotted;" @click="toggleDetail(row.id)">
                {{ detailOpen[row.id] ? 'hide' : 'show' }}
              </span>
              <router-link v-if="row.detail.commit" :to="entityRoute(row.resource_type)" style="margin-left:8px;">
                commit {{ row.detail.commit.slice(0,8) }}
              </router-link>
              <pre v-if="detailOpen[row.id]" style="margin:4px 0 0; white-space:pre-wrap;">{{ JSON.stringify(row.detail, null, 2) }}</pre>
            </template>
            <span v-else>—</span>
          </td>
        </tr>
      </table>
      <div v-if="!rows.length" class="empty">No audit entries found</div>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:12px;">
        <button class="btn" @click="prevPage" :disabled="offset === 0">Previous</button>
        <span style="font-size:12px; color:var(--color-text-muted);">Rows {{ offset + 1 }}–{{ offset + rows.length }}</span>
        <button class="btn" @click="nextPage" :disabled="rows.length < limit">Next</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api.js'
import { RESOURCE_TYPES, presetRange } from '../audit-filters.js'
import Loading from '../components/Loading.vue'

const route = useRoute()
const router = useRouter()

const resourceTypes = RESOURCE_TYPES

const ENTITY_ROUTE = {
  workflow: '/workflows',
  action: '/actions',
  connector: '/connectors',
}

function entityRoute(resourceType) {
  return ENTITY_ROUTE[resourceType] || '/audit-log'
}

const rows = ref([])
const loading = ref(true)
const error = ref(null)
const limit = ref(50)
const offset = ref(0)
const detailOpen = ref({})
const filters = ref({
  resource_type: route.query.resource_type || '',
  resource_id: route.query.resource_id || '',
  action: route.query.action || '',
  actor_name: route.query.actor_name || '',
  since: '',
  until: '',
})

const hasFilters = computed(() =>
  !!(filters.value.resource_type || filters.value.resource_id || filters.value.action ||
     filters.value.actor_name || filters.value.since || filters.value.until)
)

function toggleDetail(id) {
  detailOpen.value = { ...detailOpen.value, [id]: !detailOpen.value[id] }
}

function applyPreset(preset) {
  const { since, until } = presetRange(preset)
  // datetime-local inputs need "YYYY-MM-DDTHH:mm", not a full ISO string
  filters.value.since = since.slice(0, 16)
  filters.value.until = until.slice(0, 16)
  reload()
}

async function load() {
  loading.value = true
  try {
    const params = { limit: limit.value, offset: offset.value }
    if (filters.value.resource_type) params.resource_type = filters.value.resource_type
    if (filters.value.resource_id) params.resource_id = filters.value.resource_id
    if (filters.value.action) params.action = filters.value.action
    if (filters.value.actor_name) params.actor_name = filters.value.actor_name
    if (filters.value.since) params.since = new Date(filters.value.since).toISOString()
    if (filters.value.until) params.until = new Date(filters.value.until).toISOString()
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
  filters.value = { resource_type: '', resource_id: '', action: '', actor_name: '', since: '', until: '' }
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
