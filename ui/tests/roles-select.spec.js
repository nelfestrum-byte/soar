import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import Users from '../src/views/Users.vue'
import ApiKeys from '../src/views/ApiKeys.vue'
import { auth } from '../src/store/auth.js'
import { api } from '../src/api.js'
import { ROLES } from '../src/permissions.js'

beforeEach(() => {
  auth.checked = true
  auth.authenticated = true
  auth.role = 'admin'
  auth.username = 'root'
  vi.restoreAllMocks()
})

describe('Users role selector', () => {
  it('offers every role, including agent', async () => {
    vi.spyOn(api, 'listUsers').mockResolvedValue([
      { id: 1, username: 'ann', role: 'viewer', is_active: true, last_login_at: null },
    ])
    const wrapper = mount(Users)
    await flushPromises()

    const options = [...wrapper.find('select').element.options].map((o) => o.value)
    expect(options).toEqual(expect.arrayContaining(ROLES))
    expect(options).toContain('agent')
  })
})

describe('ApiKeys role selector', () => {
  it('offers every role, including agent', async () => {
    vi.spyOn(api, 'listApiKeys').mockResolvedValue([])
    const wrapper = mount(ApiKeys)
    await flushPromises()
    await wrapper.find('button.btn-primary').trigger('click') // "New Key" reveals the form

    const options = [...wrapper.find('select').element.options].map((o) => o.value)
    expect(options).toEqual(expect.arrayContaining(ROLES))
    expect(options).toContain('agent')
  })
})
