const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export const api = {
  getStatus: () => request('/status'),
  getWorkflows: () => request('/workflows'),
  enableWorkflow: (name) => request(`/workflows/${name}/enable`, { method: 'POST' }),
  disableWorkflow: (name) => request(`/workflows/${name}/disable`, { method: 'POST' }),
  getJobs: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/jobs${qs ? '?' + qs : ''}`)
  },
  createJob: (workflow_name, context = {}) =>
    request('/jobs', { method: 'POST', body: JSON.stringify({ workflow_name, context }) }),
  getJob: (id) => request(`/jobs/${id}`),
  cancelJob: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),
  getFiles: () => request('/files'),
  getFile: (path) => fetch(`${BASE}/files/${path}`).then(r => r.text()),
  saveFile: (path, content) =>
    request(`/files/${path}`, { method: 'PUT', body: content }),
  getLogs: (id) => fetch(`${BASE}/logs/${id}`).then(r => r.text()),
}
