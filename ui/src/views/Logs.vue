<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2>Log: {{ route.params.id.slice(0,8) }}</h2>
      <router-link to="/jobs" class="btn btn-primary" style="text-decoration:none;">Back</router-link>
    </div>
    <Loading v-if="loading" />
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <pre>{{ logs }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api.js'
import Loading from '../components/Loading.vue'

const route = useRoute()
const logs = ref('')
const loading = ref(true)
const error = ref(null)
let timer = null

function isTerminal(status) {
  return status !== 'pending' && status !== 'running'
}

async function load() {
  try {
    logs.value = await api.getLogs(route.params.id)
    error.value = null
  } catch (e) {
    error.value = e.message
  }
  loading.value = false

  try {
    const job = await api.getJob(route.params.id)
    if (!isTerminal(job.status)) timer = setTimeout(load, 2000)
  } catch {
    // job lookup is best-effort here — the log itself already loaded
  }
}

onMounted(load)
onUnmounted(() => { if (timer) clearTimeout(timer) })
</script>
