<template>
  <div>
    <div v-if="loading" class="loading">Loading history...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <table v-if="commits.length">
        <tr><th></th><th></th><th>Commit</th><th>Message</th><th>Author</th><th>When</th></tr>
        <tr v-for="c in commits" :key="c.hash">
          <td><input type="radio" name="side-a" :data-test="'radio-a-'+c.hash" :value="c.hash" v-model="sideA" /></td>
          <td><input type="radio" name="side-b" :data-test="'radio-b-'+c.hash" :value="c.hash" v-model="sideB" /></td>
          <td style="font-family:monospace; cursor:pointer;" :data-test="'commit-'+c.hash" @click="showVersion(c.hash)">
            {{ c.hash.slice(0,8) }}
          </td>
          <td>{{ c.message }}</td>
          <td>{{ c.author }}</td>
          <td style="font-size:12px; color:#999;">{{ fmt(c.timestamp) }}</td>
        </tr>
      </table>
      <div v-else class="loading">No history yet</div>

      <div v-if="version !== null" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-size:12px; color:#666;">Version {{ activeCommit.slice(0,8) }}</div>
          <button v-if="canRestore" class="btn btn-danger" data-test="restore" @click="doRestore(activeCommit)">
            Restore this version
          </button>
        </div>
        <pre data-test="version-content">{{ version }}</pre>
      </div>

      <div v-if="diff !== null" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-size:12px; color:#666;">Diff {{ sideA.slice(0,8) }} → {{ sideB.slice(0,8) }}</div>
          <button v-if="canRestore" class="btn btn-danger" data-test="restore" @click="doRestore(sideB)">
            Restore {{ sideB.slice(0,8) }}
          </button>
        </div>
        <pre data-test="diff" class="diff"><span v-for="(line, i) in diffLines" :key="i" :class="diffClass(line)">{{ line }}
</span></pre>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api.js'
import { auth } from '../store/auth.js'
import { can } from '../permissions.js'
import { notify } from '../store/toast.js'

const props = defineProps({
  entity: { type: String, required: true }, // 'workflow' | 'action' | 'connector_code' | 'connector_config'
  name: { type: String, required: true },
})
const emit = defineEmits(['restored'])

const API_KEY = { workflow: 'workflow', action: 'action', connector_code: 'connectorCode', connector_config: 'connectorConfig' }
const RESTORE_CAP = { workflow: 'restore', action: 'restore', connector_code: 'connector.code.write', connector_config: 'connector.config.write' }

const client = computed(() => api.history[API_KEY[props.entity]])
const canRestore = computed(() => can(auth.role, RESTORE_CAP[props.entity]))

const commits = ref([])
const loading = ref(true)
const error = ref(null)

const version = ref(null)
const activeCommit = ref('')
const diff = ref(null)
const sideA = ref('')
const sideB = ref('')

const diffLines = computed(() => (diff.value || '').split('\n'))

function diffClass(line) {
  if (line.startsWith('+')) return 'diff-add'
  if (line.startsWith('-')) return 'diff-del'
  return ''
}

function fmt(iso) {
  return iso ? new Date(iso).toLocaleString() : '—'
}

async function load() {
  loading.value = true
  try {
    commits.value = await client.value.getHistory(props.name)
    error.value = null
  } catch (e) {
    error.value = e.message
  }
  loading.value = false
}

async function showVersion(hash) {
  diff.value = null
  activeCommit.value = hash
  try {
    version.value = await client.value.getVersion(props.name, hash)
  } catch (e) {
    notify.error(e.message)
  }
}

watch([sideA, sideB], async ([a, b]) => {
  if (!a || !b) return
  version.value = null
  try {
    diff.value = await client.value.getDiff(props.name, a, b)
  } catch (e) {
    notify.error(e.message)
  }
})

async function doRestore(hash) {
  if (!confirm(`Restore ${props.name} to commit ${hash.slice(0,8)}?`)) return
  try {
    await client.value.restore(props.name, hash)
    notify.success('Restored — reloading history')
    version.value = null
    diff.value = null
    await load()
    emit('restored', hash)
  } catch (e) {
    notify.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.diff { white-space: pre; }
.diff-add { color: #2e7d32; }
.diff-del { color: #c62828; }
</style>
