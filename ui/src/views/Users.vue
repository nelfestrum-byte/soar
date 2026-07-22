<template>
  <div>
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Users</h2>
      <button class="btn btn-primary" @click="showNew = true">New User</button>
    </div>

    <div v-if="showNew" class="card" style="margin-bottom:12px;">
      <h2>New User</h2>
      <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
        <input v-model="newUsername" placeholder="username" style="flex:1; min-width:150px;" />
        <input v-model="newPassword" type="password" placeholder="password (min 8 chars)" style="flex:1; min-width:150px;" />
        <select v-model="newRole">
          <option value="viewer">viewer</option>
          <option value="analyst">analyst</option>
          <option value="service">service</option>
          <option value="admin">admin</option>
        </select>
        <button class="btn btn-primary" @click="createUser" :disabled="!newUsername || newPassword.length < 8 || creating">
          {{ creating ? 'Creating...' : 'Create' }}
        </button>
        <button class="btn" @click="showNew = false">Cancel</button>
      </div>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else class="card">
      <table v-if="users.length">
        <tr><th>Username</th><th>Role</th><th>Status</th><th>Last login</th><th></th></tr>
        <tr v-for="u in users" :key="u.id">
          <td>
            {{ u.username }}
            <span v-if="u.username === auth.username" class="badge badge-running" style="margin-left:6px;">you</span>
          </td>
          <td>
            <select :value="u.role" @change="changeRole(u, $event.target.value)">
              <option value="viewer">viewer</option>
              <option value="analyst">analyst</option>
              <option value="service">service</option>
              <option value="admin">admin</option>
            </select>
          </td>
          <td>
            <span class="badge" :class="u.is_active ? 'badge-completed' : 'badge-cancelled'">
              {{ u.is_active ? 'active' : 'inactive' }}
            </span>
          </td>
          <td>{{ u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—' }}</td>
          <td style="display:flex; gap:4px; flex-wrap:wrap;">
            <button
              class="btn"
              style="font-size:11px;"
              :disabled="u.username === auth.username"
              :title="u.username === auth.username ? 'Cannot deactivate your own account' : ''"
              @click="toggleActive(u)"
            >{{ u.is_active ? 'Deactivate' : 'Activate' }}</button>
            <button class="btn" style="font-size:11px;" @click="startReset(u)">Reset password</button>
          </td>
        </tr>
      </table>
      <div v-else class="loading">No users yet</div>
    </div>

    <div v-if="resetTarget" class="card" style="margin-top:12px;">
      <h2>Reset password — {{ resetTarget.username }}</h2>
      <div style="display:flex; gap:8px; margin-top:8px;">
        <input v-model="resetPassword" type="password" placeholder="new password (min 8 chars)" style="flex:1;" />
        <button class="btn btn-primary" :disabled="resetPassword.length < 8" @click="submitReset">Save</button>
        <button class="btn" @click="resetTarget = null">Cancel</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api.js'
import { auth } from '../store/auth.js'

const users = ref([])
const loading = ref(true)
const error = ref(null)
const showNew = ref(false)
const newUsername = ref('')
const newPassword = ref('')
const newRole = ref('viewer')
const creating = ref(false)
const resetTarget = ref(null)
const resetPassword = ref('')

async function loadUsers() {
  loading.value = true
  try { users.value = await api.listUsers() }
  catch (e) { error.value = e.message }
  loading.value = false
}

async function createUser() {
  creating.value = true
  error.value = null
  try {
    await api.createUser(newUsername.value, newPassword.value, newRole.value)
    showNew.value = false
    newUsername.value = ''
    newPassword.value = ''
    newRole.value = 'viewer'
    await loadUsers()
  } catch (e) {
    error.value = e.message
  }
  creating.value = false
}

async function changeRole(user, role) {
  if (role === user.role) return
  try {
    await api.updateUser(user.id, { role })
    await loadUsers()
  } catch (e) {
    error.value = e.message
    await loadUsers()
  }
}

async function toggleActive(user) {
  try {
    await api.updateUser(user.id, { is_active: !user.is_active })
    await loadUsers()
  } catch (e) {
    error.value = e.message
  }
}

function startReset(user) {
  resetTarget.value = user
  resetPassword.value = ''
}

async function submitReset() {
  try {
    await api.updateUser(resetTarget.value.id, { password: resetPassword.value })
    resetTarget.value = null
    resetPassword.value = ''
  } catch (e) {
    error.value = e.message
  }
}

onMounted(loadUsers)
</script>
