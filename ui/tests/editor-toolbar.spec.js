import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import Workflows from '../src/views/Workflows.vue'
import Actions from '../src/views/Actions.vue'
import Connectors from '../src/views/Connectors.vue'
import { auth } from '../src/store/auth.js'
import { api } from '../src/api.js'

function withRouter(component) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component },
      { path: '/jobs', component: { template: '<div />' } },
      { path: '/audit-log', component: { template: '<div />' } },
    ],
  })
  return router
}

beforeEach(() => {
  auth.checked = true
  auth.authenticated = true
  auth.username = 'someone'
  auth.role = 'admin'
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('editor toolbar', () => {
  it('renders a sticky toolbar with tabs and Save/Close once a workflow is opened', async () => {
    vi.spyOn(api, 'getWorkflows').mockResolvedValue([{ name: 'wf1', type: 'manual', class_name: 'Wf1' }])
    vi.spyOn(api, 'getStatus').mockResolvedValue({ scheduler: { next_runs: [] } })
    vi.spyOn(api, 'getWorkflowCode').mockResolvedValue({ content: 'print(1)' })

    const router = withRouter(Workflows)
    router.push('/')
    await router.isReady()
    const wrapper = mount(Workflows, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('table .btn-primary').trigger('click')
    await flushPromises()

    const toolbar = wrapper.find('.editor-toolbar')
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.text()).toContain('Code')
    expect(toolbar.text()).toContain('History')
    expect(toolbar.text()).toContain('Save')
  })

  it('renders a sticky toolbar once an action is opened', async () => {
    vi.spyOn(api, 'getActions').mockResolvedValue([{ name: 'act1', summary: '' }])
    vi.spyOn(api, 'getAction').mockResolvedValue({ content: 'print(1)' })

    const router = withRouter(Actions)
    router.push('/')
    await router.isReady()
    const wrapper = mount(Actions, { global: { plugins: [router] } })
    await flushPromises()

    const clickableName = wrapper.findAll('span').find((s) => (s.attributes('style') || '').includes('cursor'))
    await clickableName.trigger('click')
    await flushPromises()

    const toolbar = wrapper.find('.editor-toolbar')
    expect(toolbar.exists()).toBe(true)
    expect(toolbar.text()).toContain('Signature')
  })

  it('renders a sticky toolbar for both code and config panels of a connector', async () => {
    vi.spyOn(api, 'getConnectors').mockResolvedValue([{ name: 'conn1', class_name: 'Conn1', has_config: true }])
    vi.spyOn(api, 'getConnectorCode').mockResolvedValue({ content: 'print(1)' })
    vi.spyOn(api, 'getConnectorConfig').mockResolvedValue({ content: 'instances: {}' })
    vi.spyOn(api, 'getConnectorSchema').mockResolvedValue({ fields: [] })

    const router = withRouter(Connectors)
    router.push('/')
    await router.isReady()
    const wrapper = mount(Connectors, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.find('table .btn-primary').trigger('click')
    await flushPromises()
    expect(wrapper.find('.editor-toolbar').exists()).toBe(true)

    await wrapper.find('.btn-success').trigger('click')
    await flushPromises()
    expect(wrapper.find('.editor-toolbar').exists()).toBe(true)
  })
})
