const BASE = '/api'
const ACCESS_KEY = 'soar_access_token'
const REFRESH_KEY = 'soar_refresh_token'

const getAccessToken = () => localStorage.getItem(ACCESS_KEY) || ''
const getRefreshToken = () => localStorage.getItem(REFRESH_KEY) || ''

function setTokens(access, refresh) {
  if (access) localStorage.setItem(ACCESS_KEY, access)
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh)
}

function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

function authHeaders() {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

async function tryRefresh() {
  const refresh_token = getRefreshToken()
  if (!refresh_token) return false
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token }),
    })
    if (!res.ok) { clearTokens(); return false }
    const data = await res.json()
    setTokens(data.access_token, data.refresh_token)
    return true
  } catch {
    clearTokens()
    return false
  }
}

async function request(path, options = {}, allowRetry = true) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...options.headers },
  })

  if (res.status === 401 && allowRetry && path !== '/auth/login' && path !== '/auth/refresh') {
    if (await tryRefresh()) return request(path, options, false)
    clearTokens()
    if (onUnauthorized) onUnauthorized()
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const e = new Error(err.detail || 'Request failed')
    e.status = res.status
    throw e
  }
  return res.json()
}

export const api = {
  getStatus: () => request('/status'),
  getWorkflows: () => request('/workflows'),
  reloadWorkflows: () => request('/workflows/reload', { method: 'POST' }),
  enableWorkflow: (name) => request(`/workflows/${name}/enable`, { method: 'POST' }),
  disableWorkflow: (name) => request(`/workflows/${name}/disable`, { method: 'POST' }),
  getWorkflowCode: (name) => request(`/workflows/${name}/code`),
  saveWorkflowCode: (name, content) =>
    request(`/workflows/${name}/code`, { method: 'PUT', body: JSON.stringify({ code: content }) }),
  deleteWorkflowCode: (name) => request(`/workflows/${name}/code`, { method: 'DELETE' }),
  getWorkflowTemplate: (name, type = 'scheduled') =>
    request(`/workflows/code/template?name=${name}&wf_type=${type}`),
  getJobs: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/jobs${qs ? '?' + qs : ''}`)
  },
  createJob: (workflow_name, context = {}) =>
    request('/jobs', { method: 'POST', body: JSON.stringify({ workflow_name, context }) }),
  getJob: (id) => request(`/jobs/${id}`),
  cancelJob: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),
  getActions: () => request('/actions'),
  getAction: (name) => request(`/actions/${name}`),
  saveAction: (name, content) =>
    request(`/actions/${name}`, { method: 'PUT', body: JSON.stringify({ code: content }) }),
  deleteAction: (name) => request(`/actions/${name}`, { method: 'DELETE' }),
  getActionTemplate: (name) => request(`/actions/template?name=${name}`),
  getLogs: (id) => request(`/logs/${id}`),
  getConnectors: () => request('/connectors'),
  getConnectorCode: (name) => request(`/connectors/${name}/code`),
  saveConnectorCode: (name, content) =>
    request(`/connectors/${name}/code`, { method: 'PUT', body: content }),
  getConnectorConfig: (name) => request(`/connectors/${name}/config`),
  saveConnectorConfig: (name, content) =>
    request(`/connectors/${name}/config`, { method: 'PUT', body: content }),
  createConnector: (name, className = '') =>
    request(`/connectors/${name}?class_name=${className}`, { method: 'POST' }),
  deleteConnector: (name) => request(`/connectors/${name}`, { method: 'DELETE' }),
  preview: (spec) => request('/connectors/preview', { method: 'POST', body: JSON.stringify({ spec }) }),
  previewUrl: (url) => request(`/connectors/preview?url=${encodeURIComponent(url)}`),
  generateConnector: (spec, name) =>
    request('/connectors/generate', { method: 'POST', body: JSON.stringify({ spec, name }) }),
  exportEntities: async () => {
    const res = await fetch(`${BASE}/transfer/export`, { method: 'POST', headers: authHeaders() })
    if (!res.ok) throw new Error('Export failed')
    return res.blob()
  },
  importEntities: async (file, force = false) => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${BASE}/transfer/import?force=${force}`, {
      method: 'POST',
      headers: authHeaders(),
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || 'Import failed')
    }
    return res.json()
  },

  getTools: () => request('/tools'),
  getTool: (name) => request(`/tools/${name}`),

  getAuditLog: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/audit-log${qs ? '?' + qs : ''}`)
  },

  login: async (username, password) => {
    const data = await request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setTokens(data.access_token, data.refresh_token)
    return data
  },
  logout: async () => {
    const refresh_token = getRefreshToken()
    clearTokens()
    if (refresh_token) {
      try {
        await fetch(`${BASE}/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token }),
        })
      } catch {
        // best-effort — tokens are already cleared client-side
      }
    }
  },
  me: () => request('/auth/me'),
  listApiKeys: () => request('/auth/keys'),
  createApiKey: (name, role, expires_at = null) =>
    request('/auth/keys', { method: 'POST', body: JSON.stringify({ name, role, expires_at }) }),
  deleteApiKey: (id) => request(`/auth/keys/${id}`, { method: 'DELETE' }),
}
