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
  reloadWorkflows: () => request('/workflows/reload', { method: 'POST' }),
  enableWorkflow: (name) => request(`/workflows/${name}/enable`, { method: 'POST' }),
  disableWorkflow: (name) => request(`/workflows/${name}/disable`, { method: 'POST' }),
  getWorkflowCode: (name) => request(`/workflows/${name}/code`),
  saveWorkflowCode: (name, content) =>
    request(`/workflows/${name}/code`, { method: 'PUT', body: content }),
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
    request(`/actions/${name}`, { method: 'PUT', body: content }),
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
    const res = await fetch(`${BASE}/transfer/export`, { method: 'POST' })
    if (!res.ok) throw new Error('Export failed')
    return res.blob()
  },
  importEntities: async (file, force = false) => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${BASE}/transfer/import?force=${force}`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || 'Import failed')
    }
    return res.json()
  },
}
