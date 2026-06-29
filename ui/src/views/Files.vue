<template>
  <div>
    <h2 style="margin-bottom:12px;">Files</h2>
    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <template v-else>
      <div class="card" v-for="(items, dir) in tree" :key="dir">
        <h2>{{ dir }}/</h2>
        <div v-if="items && Object.keys(items).length">
          <div v-for="(content, name) in items" :key="name"
               style="padding:4px 8px; cursor:pointer; font-size:13px; font-family:monospace;"
               :style="{background: selected===dir+'/'+name ? '#e3f2fd' : ''}"
               @click="loadFile(dir+'/'+name)">
            {{ name }}
          </div>
        </div>
        <div v-else class="loading">Empty</div>
      </div>

      <div v-if="selected" class="card" style="margin-top:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h2 style="margin:0;">{{ selected }}</h2>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-primary" @click="save" :disabled="saving">
              {{ saving ? 'Saving...' : 'Save' }}
            </button>
          </div>
        </div>
        <textarea v-model="content" style="width:100%; min-height:400px; font-family:monospace; font-size:12px; padding:8px; border:1px solid #ddd; border-radius:4px; resize:vertical;"></textarea>
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

const tree = ref({})
const loading = ref(true)
const error = ref(null)
const selected = ref('')
const content = ref('')
const saving = ref(false)
const saveResult = ref(null)

async function loadTree() {
  try { tree.value = await api.getFiles() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function loadFile(path) {
  selected.value = path
  try { content.value = await api.getFile(path) }
  catch (e) { content.value = `Error: ${e.message}` }
}

async function save() {
  saving.value = true
  saveResult.value = null
  try {
    const res = await api.saveFile(selected.value, content.value)
    saveResult.value = { success: true, commit: res.commit }
  } catch (e) {
    saveResult.value = { success: false, error: e.message }
  }
  saving.value = false
}

onMounted(loadTree)
</script>
