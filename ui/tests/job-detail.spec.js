import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobDetail from '../src/views/JobDetail.vue'
import { auth } from '../src/store/auth.js'
import { api } from '../src/api.js'

const TRACEBACK = `Traceback (most recent call last):
  File "/opt/soar/workflows/enrich_ip.py", line 42, in run
    result = self.vt.lookup(ip)
KeyError: 'data'`

function job(overrides = {}) {
  return {
    id: 'job-1234-5678',
    workflow_name: 'enrich_ip',
    workflow_type: 'manual',
    triggered_by: 'admin',
    context: { ip: '8.8.8.8' },
    status: 'failed',
    timeout: 300,
    triggered_at: '2026-07-29T10:00:00Z',
    started_at: '2026-07-29T10:00:01Z',
    finished_at: '2026-07-29T10:00:09Z',
    duration_seconds: 8.2,
    result_success: false,
    result_data: null,
    result_error: TRACEBACK,
    log_path: '/var/log/soar/jobs/enrich_ip/job-1234-5678.log',
    ...overrides,
  }
}

async function mountDetail(jobPayload, { role = 'admin', log = 'log line\n' } = {}) {
  auth.checked = true
  auth.authenticated = true
  auth.username = 'someone'
  auth.role = role

  vi.spyOn(api, 'getJob').mockResolvedValue(jobPayload)
  vi.spyOn(api, 'getLogs').mockResolvedValue(log)

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/jobs/:id', component: JobDetail },
      { path: '/jobs', component: { template: '<div />' } },
      { path: '/logs/:id', component: { template: '<div />' } },
      { path: '/audit-log', component: { template: '<div />' } },
    ],
  })
  router.push(`/jobs/${jobPayload.id}`)
  await router.isReady()

  const wrapper = mount(JobDetail, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('failed job', () => {
  it('shows the whole traceback without opening the log', async () => {
    const wrapper = await mountDetail(job())
    const tb = wrapper.find('[data-test="traceback"]')

    expect(tb.exists()).toBe(true)
    expect(tb.text()).toContain("KeyError: 'data'")
    expect(tb.text()).toContain('line 42, in run')
  })

  it('shows the job context once expanded (collapsed by default)', async () => {
    const wrapper = await mountDetail(job())
    expect(wrapper.find('[data-test="context"]').exists()).toBe(false)

    const header = wrapper.findAll('h2').find((h) => h.text().includes('Context'))
    await header.trigger('click')

    expect(wrapper.find('[data-test="context"]').text()).toContain('8.8.8.8')
  })
})

describe('completed job', () => {
  it('shows result data and no error block', async () => {
    const wrapper = await mountDetail(job({
      status: 'completed',
      result_success: true,
      result_error: null,
      result_data: { verdict: 'clean' },
    }))

    expect(wrapper.find('[data-test="traceback"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="result-data"]').text()).toContain('verdict')
  })
})

describe('log', () => {
  it('is fetched for a role allowed to read it', async () => {
    const wrapper = await mountDetail(job(), { role: 'analyst', log: 'hello from the log' })
    expect(api.getLogs).toHaveBeenCalledWith('job-1234-5678')
    expect(wrapper.find('[data-test="log"]').text()).toContain('hello from the log')
  })

  // orchestrator/api/logs.py:13 — viewer is not in _RW
  it('is not requested for viewer', async () => {
    const wrapper = await mountDetail(job(), { role: 'viewer' })
    expect(api.getLogs).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="log"]').exists()).toBe(false)
  })
})

describe('auto-refresh', () => {
  it('keeps polling while the job is running', async () => {
    vi.useFakeTimers()
    const wrapper = await mountDetail(job({ status: 'running', result_error: null, finished_at: null }))
    expect(api.getJob).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(api.getJob.mock.calls.length).toBeGreaterThan(1)
    wrapper.unmount()
  })

  it('stops once the job reached a terminal status', async () => {
    vi.useFakeTimers()
    const wrapper = await mountDetail(job({ status: 'failed' }))
    const afterMount = api.getJob.mock.calls.length

    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()

    expect(api.getJob.mock.calls.length).toBe(afterMount)
    wrapper.unmount()
  })

  it('stops polling after unmount', async () => {
    vi.useFakeTimers()
    const wrapper = await mountDetail(job({ status: 'running', result_error: null, finished_at: null }))
    wrapper.unmount()
    const afterUnmount = api.getJob.mock.calls.length

    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()

    expect(api.getJob.mock.calls.length).toBe(afterUnmount)
  })
})
