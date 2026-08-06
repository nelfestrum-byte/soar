import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import Prompts from '../src/views/Prompts.vue'
import CodeEditor from '../src/components/CodeEditor.vue'
import { auth } from '../src/store/auth.js'
import { api } from '../src/api.js'

function setup(role) {
  auth.checked = true
  auth.authenticated = true
  auth.role = role
  auth.username = 'someone'
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('system prompt', () => {
  it('shows the content read-only', async () => {
    setup('viewer')
    vi.spyOn(api, 'getPromptSystem').mockResolvedValue({ content: 'You are a SOC analyst.' })
    vi.spyOn(api, 'getPromptUser').mockResolvedValue({ content: null })

    const wrapper = mount(Prompts)
    await flushPromises()

    expect(wrapper.find('[data-test="system-prompt"]').text()).toContain('SOC analyst')
  })

  // orchestrator/api/prompts.py:22-25 — 404 means "not configured", not an error
  it('shows a not-configured message on 404, not an error banner', async () => {
    setup('viewer')
    const err = new Error('System prompt not configured')
    err.status = 404
    vi.spyOn(api, 'getPromptSystem').mockRejectedValue(err)
    vi.spyOn(api, 'getPromptUser').mockResolvedValue({ content: null })

    const wrapper = mount(Prompts)
    await flushPromises()

    expect(wrapper.find('[data-test="system-not-configured"]').exists()).toBe(true)
    expect(wrapper.find('.error').exists()).toBe(false)
  })
})

describe('user prompt', () => {
  it('renders a null content as an empty field, not the string "null"', async () => {
    setup('admin')
    vi.spyOn(api, 'getPromptSystem').mockResolvedValue({ content: 'sys' })
    vi.spyOn(api, 'getPromptUser').mockResolvedValue({ content: null })

    const wrapper = mount(Prompts)
    await flushPromises()

    expect(wrapper.findComponent(CodeEditor).props('modelValue')).toBe('')
  })

  it('shows Save only for a role with prompt.write', async () => {
    vi.spyOn(api, 'getPromptSystem').mockResolvedValue({ content: 'sys' })
    vi.spyOn(api, 'getPromptUser').mockResolvedValue({ content: 'be terse' })

    setup('viewer')
    let wrapper = mount(Prompts)
    await flushPromises()
    expect(wrapper.find('[data-test="save-user-prompt"]').exists()).toBe(false)
    expect(wrapper.findComponent(CodeEditor).props('readOnly')).toBe(true)

    setup('admin')
    wrapper = mount(Prompts)
    await flushPromises()
    expect(wrapper.find('[data-test="save-user-prompt"]').exists()).toBe(true)
    expect(wrapper.findComponent(CodeEditor).props('readOnly')).toBe(false)
  })

  it('saves and shows the commit hash', async () => {
    setup('admin')
    vi.spyOn(api, 'getPromptSystem').mockResolvedValue({ content: 'sys' })
    vi.spyOn(api, 'getPromptUser').mockResolvedValue({ content: 'be terse' })
    vi.spyOn(api, 'savePromptUser').mockResolvedValue({ status: 'saved', commit: 'abc123' })

    const wrapper = mount(Prompts)
    await flushPromises()
    await wrapper.find('[data-test="save-user-prompt"]').trigger('click')
    await flushPromises()

    expect(api.savePromptUser).toHaveBeenCalledWith('be terse')
    expect(wrapper.text()).toContain('abc123')
  })
})
