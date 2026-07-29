import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import App from '../src/App.vue'
import { auth } from '../src/store/auth.js'
import { routeAllowed } from '../src/router-guard.js'

const Blank = { template: '<div />' }

const routes = [
  { path: '/', component: Blank },
  { path: '/workflows', component: Blank },
  { path: '/jobs', component: Blank },
  { path: '/actions', component: Blank },
  { path: '/connectors', component: Blank },
  { path: '/tools', component: Blank },
  { path: '/prompts', component: Blank },
  { path: '/generate', component: Blank, meta: { cap: 'connector.manage' } },
  { path: '/settings', component: Blank, meta: { cap: 'transfer' } },
  { path: '/api-keys', component: Blank, meta: { cap: 'auth.admin' } },
  { path: '/users', component: Blank, meta: { cap: 'auth.admin' } },
  { path: '/audit-log', component: Blank, meta: { cap: 'audit.read' } },
  { path: '/login', component: Blank },
]

async function navFor(role) {
  auth.checked = true
  auth.authenticated = true
  auth.username = 'someone'
  auth.role = role
  auth.noAuthMode = false

  const router = createRouter({ history: createMemoryHistory(), routes })
  router.push('/')
  await router.isReady()

  const wrapper = mount(App, { global: { plugins: [router] } })
  return wrapper.find('nav').text()
}

beforeEach(() => {
  auth.checked = false
  auth.authenticated = false
  auth.role = ''
})

describe('navigation', () => {
  it('shows admin every section', async () => {
    const nav = await navFor('admin')
    for (const label of ['Workflows', 'Jobs', 'Actions', 'Connectors', 'Tools',
      'Generate', 'Settings', 'Users', 'API Keys', 'Audit Log']) {
      expect(nav, label).toContain(label)
    }
  })

  it('hides every administrative section from viewer', async () => {
    const nav = await navFor('viewer')
    for (const label of ['Generate', 'Settings', 'Users', 'API Keys', 'Audit Log']) {
      expect(nav, label).not.toContain(label)
    }
    expect(nav).toContain('Workflows')
    expect(nav).toContain('Jobs')
  })

  it('hides connector generation and transfer from analyst', async () => {
    const nav = await navFor('analyst')
    expect(nav).not.toContain('Generate')
    expect(nav).not.toContain('Settings')
    expect(nav).not.toContain('Audit Log')
    expect(nav).toContain('Workflows')
  })

  it('shows the role next to the username', async () => {
    const nav = await navFor('analyst')
    expect(nav).toContain('analyst')
  })
})

describe('routeAllowed', () => {
  const route = (path) => routes.find((r) => r.path === path)

  it('lets anyone into a route without a capability', () => {
    expect(routeAllowed(route('/jobs'), 'viewer')).toBe(true)
    expect(routeAllowed(route('/tools'), 'viewer')).toBe(true)
  })

  it('keeps viewer out of the administrative routes by URL', () => {
    expect(routeAllowed(route('/users'), 'viewer')).toBe(false)
    expect(routeAllowed(route('/api-keys'), 'viewer')).toBe(false)
    expect(routeAllowed(route('/audit-log'), 'viewer')).toBe(false)
    expect(routeAllowed(route('/settings'), 'viewer')).toBe(false)
  })

  it('keeps agent out of audit and transfer', () => {
    expect(routeAllowed(route('/audit-log'), 'agent')).toBe(false)
    expect(routeAllowed(route('/settings'), 'agent')).toBe(false)
    expect(routeAllowed(route('/generate'), 'agent')).toBe(true)
  })

  it('admits admin everywhere', () => {
    for (const r of routes) expect(routeAllowed(r, 'admin'), r.path).toBe(true)
  })
})
