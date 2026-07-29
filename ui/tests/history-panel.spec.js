import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import HistoryPanel from '../src/components/HistoryPanel.vue'
import { auth } from '../src/store/auth.js'
import { api } from '../src/api.js'

const COMMITS = [
  { hash: 'abc12345', message: 'Update workflow', author: 'admin', timestamp: '2026-07-29T10:00:00Z' },
  { hash: 'def67890', message: 'Initial version', author: 'admin', timestamp: '2026-07-28T09:00:00Z' },
]

function mountPanel({ role = 'admin', entity = 'workflow', name = 'enrich_ip' } = {}) {
  auth.checked = true
  auth.authenticated = true
  auth.role = role

  vi.spyOn(api.history[toKey(entity)], 'getHistory').mockResolvedValue(COMMITS)
  vi.spyOn(api.history[toKey(entity)], 'getVersion').mockResolvedValue('print("v1")')
  vi.spyOn(api.history[toKey(entity)], 'getDiff').mockResolvedValue('-old\n+new')
  vi.spyOn(api.history[toKey(entity)], 'restore').mockResolvedValue({ status: 'restored', commit: 'def67890' })

  return mount(HistoryPanel, { props: { entity, name } })
}

function toKey(entity) {
  return { workflow: 'workflow', action: 'action', connector_code: 'connectorCode', connector_config: 'connectorConfig' }[entity]
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('HistoryPanel', () => {
  it('lists commits newest first as given by the backend', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const text = wrapper.text()
    expect(text.indexOf('abc12345')).toBeLessThan(text.indexOf('def67890'))
  })

  it('shows a version on click', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-test="commit-abc12345"]').trigger('click')
    await flushPromises()
    expect(api.history.workflow.getVersion).toHaveBeenCalledWith('enrich_ip', 'abc12345')
    expect(wrapper.find('[data-test="version-content"]').text()).toContain('print')
  })

  it('shows a diff once two commits are picked', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-test="radio-a-abc12345"]').setValue(true)
    await wrapper.find('[data-test="radio-b-def67890"]').setValue(true)
    await flushPromises()
    expect(api.history.workflow.getDiff).toHaveBeenCalledWith('enrich_ip', 'abc12345', 'def67890')
    expect(wrapper.find('[data-test="diff"]').exists()).toBe(true)
  })

  // BAGFIX B3 — only literal admin writes connector code
  it('hides Restore for a role without the restore capability', async () => {
    const wrapper = mountPanel({ role: 'agent', entity: 'connector_code', name: 'ssh' })
    await flushPromises()
    expect(wrapper.find('[data-test="restore"]').exists()).toBe(false)
  })

  it('shows Restore for admin and calls the api on confirm', async () => {
    vi.stubGlobal('confirm', () => true)
    const wrapper = mountPanel({ role: 'admin' })
    await flushPromises()
    await wrapper.find('[data-test="commit-abc12345"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="restore"]').trigger('click')
    await flushPromises()
    expect(api.history.workflow.restore).toHaveBeenCalledWith('enrich_ip', 'abc12345')
  })

  it('does not restore when the confirm dialog is declined', async () => {
    vi.stubGlobal('confirm', () => false)
    const wrapper = mountPanel({ role: 'admin' })
    await flushPromises()
    await wrapper.find('[data-test="commit-abc12345"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="restore"]').trigger('click')
    await flushPromises()
    expect(api.history.workflow.restore).not.toHaveBeenCalled()
  })
})
