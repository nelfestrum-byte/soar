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
  getActions: () => request('/actions'),
  getAction: (name) => request(`/actions/${name}`),
  saveAction: (name, content) =>
    request(`/actions/${name}`, { method: 'PUT', body: content }),
  deleteAction: (name) => request(`/actions/${name}`, { method: 'DELETE' }),
  getActionTemplate: (name) => request(`/actions/template?name=${name}`),
  getWorkflowFiles: () => request('/workflow-files'),
  getWorkflowFile: (name) => request(`/workflow-files/${name}`),
  saveWorkflowFile: (name, content) =>
    request(`/workflow-files/${name}`, { method: 'PUT', body: content }),
  deleteWorkflowFile: (name) => request(`/workflow-files/${name}`, { method: 'DELETE' }),
  getWorkflowTemplate: (name, type = 'scheduled') =>
    request(`/workflow-files/template?name=${name}&wf_type=${type}`),
}
