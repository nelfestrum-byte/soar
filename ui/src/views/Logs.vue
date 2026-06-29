<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2>Log: {{ $route.params.id.slice(0,8) }}</h2>
      <router-link to="/jobs" class="btn btn-primary" style="text-decoration:none;">Back</router-link>
    </div>
    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <pre>{{ logs }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api.js'

const route = useRoute()
const logs = ref('')
const loading = ref(true)
const error = ref(null)

onMounted(async () => {
  try { logs.value = await api.getLogs(route.params.id) }
  catch (e) { error.value = e.message }
  loading.value = false
})
</script>
