<template>
  <div>
    <h2 style="margin-bottom:12px;">Prompts</h2>

    <div class="card">
      <h2>System prompt</h2>
      <Loading v-if="systemLoading" />
      <div v-else-if="systemNotConfigured" data-test="system-not-configured" class="empty">
        Системный промпт не настроен (`soar.system_prompt_path` не задан или файл отсутствует)
      </div>
      <div v-else-if="systemError" class="error">{{ systemError }}</div>
      <pre v-else data-test="system-prompt">{{ systemContent }}</pre>
    </div>

    <div class="card" style="margin-top:12px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <h2 style="margin:0;">User prompt</h2>
        <button v-if="canWrite" class="btn btn-primary" data-test="save-user-prompt" @click="save" :disabled="saving">
          {{ saving ? 'Saving...' : 'Save' }}
        </button>
      </div>
      <Loading v-if="userLoading" />
      <textarea v-else v-model="userContent" :readonly="!canWrite" data-test="user-prompt-editor"
                style="width:100%; min-height:300px; font-family:var(--font-mono); font-size:12px; padding:8px; border:1px solid var(--color-border); border-radius:4px; resize:vertical;"
                placeholder="Промпт не задан"></textarea>
      <div v-if="saveResult" style="margin-top:8px; font-size:13px;">
        <span v-if="saveResult.success" style="color:var(--color-result-ok);">Saved (commit: {{ saveResult.commit }})</span>
        <span v-else style="color:var(--color-result-fail);">Error: {{ saveResult.error }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'
import { auth } from '../store/auth.js'
import { can } from '../permissions.js'
import Loading from '../components/Loading.vue'

const canWrite = computed(() => can(auth.role, 'prompt.write'))

const systemLoading = ref(true)
const systemContent = ref('')
const systemError = ref(null)
const systemNotConfigured = ref(false)

const userLoading = ref(true)
const userContent = ref('')
const saving = ref(false)
const saveResult = ref(null)

async function loadSystem() {
  try {
    const res = await api.getPromptSystem()
    systemContent.value = res.content
  } catch (e) {
    if (e.status === 404) systemNotConfigured.value = true
    else systemError.value = e.message
  }
  systemLoading.value = false
}

async function loadUser() {
  try {
    const res = await api.getPromptUser()
    userContent.value = res.content || ''
  } catch (e) {
    userContent.value = ''
  }
  userLoading.value = false
}

async function save() {
  saving.value = true
  saveResult.value = null
  try {
    const res = await api.savePromptUser(userContent.value)
    saveResult.value = { success: true, commit: res.commit }
  } catch (e) {
    saveResult.value = { success: false, error: e.message }
  }
  saving.value = false
}

onMounted(() => { loadSystem(); loadUser() })
</script>
