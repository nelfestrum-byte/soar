<template>
  <div class="login-wrap">
    <div class="card login-card">
      <h2>Sign in</h2>
      <form @submit.prevent="submit">
        <div class="field">
          <label>Username</label>
          <input v-model="username" autofocus autocomplete="username" />
        </div>
        <div class="field">
          <label>Password</label>
          <input v-model="password" type="password" autocomplete="current-password" />
        </div>
        <button class="btn btn-primary" style="width:100%;" :disabled="!username || !password || loading">
          {{ loading ? 'Signing in...' : 'Sign in' }}
        </button>
        <div v-if="error" class="error" style="margin-top:8px;">{{ error }}</div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from '../api.js'
import { checkAuth } from '../store/auth.js'

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const router = useRouter()
const route = useRoute()

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await api.login(username.value, password.value)
    await checkAuth()
    router.push(route.query.redirect || '/')
  } catch (e) {
    error.value = e.message
  }
  loading.value = false
}
</script>

<style scoped>
.login-wrap { display: flex; justify-content: center; margin-top: 80px; }
.login-card { width: 320px; }
.field { margin-bottom: 12px; display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: 12px; color: #666; }
.field input { width: 100%; box-sizing: border-box; }
</style>
