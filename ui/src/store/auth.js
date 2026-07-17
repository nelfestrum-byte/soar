import { reactive } from 'vue'
import { api } from '../api.js'

export const auth = reactive({
  checked: false,
  authenticated: false,
  username: '',
  role: '',
  noAuthMode: false,
})

export async function checkAuth() {
  try {
    const me = await api.me()
    auth.authenticated = true
    auth.username = me.username
    auth.role = me.role
    auth.noAuthMode = false
  } catch (e) {
    if (e.status === 403) {
      // secret_key not configured on the backend — anonymous admin, no login needed
      auth.authenticated = true
      auth.username = 'anonymous'
      auth.role = 'admin'
      auth.noAuthMode = true
    } else {
      auth.authenticated = false
      auth.username = ''
      auth.role = ''
      auth.noAuthMode = false
    }
  }
  auth.checked = true
}

export function resetAuth() {
  auth.authenticated = false
  auth.username = ''
  auth.role = ''
  auth.noAuthMode = false
}
