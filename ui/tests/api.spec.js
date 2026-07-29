import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, setUnauthorizedHandler } from '../src/api.js'
import { setSessionRole } from '../src/session.js'

const ACCESS_KEY = 'soar_access_token'
const REFRESH_KEY = 'soar_refresh_token'

function jsonRes(body, status = 200) {
  return {
    ok: status < 400,
    status,
    statusText: 'status',
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

// GET /logs/{id} is a PlainTextResponse — res.json() throws on it
function textRes(body, status = 200) {
  return {
    ok: status < 400,
    status,
    statusText: 'status',
    json: async () => { throw new SyntaxError('Unexpected token l in JSON at position 0') },
    text: async () => body,
  }
}

function authHeaderOf(call) {
  return call[1].headers.Authorization
}

beforeEach(() => {
  localStorage.clear()
  setUnauthorizedHandler(null)
  setSessionRole('')
  vi.restoreAllMocks()
})

describe('getLogs', () => {
  it('returns the log as plain text', async () => {
    localStorage.setItem(ACCESS_KEY, 'access-1')
    globalThis.fetch = vi.fn().mockResolvedValue(textRes('line one\nline two\n'))

    await expect(api.getLogs('job-abc')).resolves.toBe('line one\nline two\n')
    expect(globalThis.fetch.mock.calls[0][0]).toBe('/api/logs/job-abc')
  })

  it('reports a missing log as an error, not as text', async () => {
    localStorage.setItem(ACCESS_KEY, 'access-1')
    globalThis.fetch = vi.fn().mockResolvedValue(jsonRes({ detail: 'Log file not found' }, 404))

    await expect(api.getLogs('job-abc')).rejects.toThrow('Log file not found')
  })
})

describe('401 handling', () => {
  it('refreshes once and replays the original request', async () => {
    localStorage.setItem(ACCESS_KEY, 'stale')
    localStorage.setItem(REFRESH_KEY, 'refresh-1')

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(jsonRes({ detail: 'Not authenticated' }, 401))
      .mockResolvedValueOnce(jsonRes({ access_token: 'fresh', refresh_token: 'refresh-2' }))
      .mockResolvedValueOnce(jsonRes([{ id: 'job-1' }]))

    await expect(api.getJobs()).resolves.toEqual([{ id: 'job-1' }])

    const calls = globalThis.fetch.mock.calls
    expect(calls).toHaveLength(3)
    expect(calls[1][0]).toBe('/api/auth/refresh')
    expect(authHeaderOf(calls[2])).toBe('Bearer fresh')
    expect(localStorage.getItem(ACCESS_KEY)).toBe('fresh')
    expect(localStorage.getItem(REFRESH_KEY)).toBe('refresh-2')
  })

  it('clears tokens and notifies once when the refresh also fails', async () => {
    localStorage.setItem(ACCESS_KEY, 'stale')
    localStorage.setItem(REFRESH_KEY, 'refresh-1')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)

    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(jsonRes({ detail: 'Not authenticated' }, 401))
      .mockResolvedValueOnce(jsonRes({ detail: 'Invalid credentials' }, 401))

    await expect(api.getJobs()).rejects.toThrow()

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(ACCESS_KEY)).toBeNull()
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull()
  })

  it('does not try to refresh a failed login', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonRes({ detail: 'Invalid credentials' }, 401))

    await expect(api.login('bob', 'wrong')).rejects.toThrow('Invalid credentials')
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
  })
})

describe('403 handling', () => {
  it('names the role that lacks the right', async () => {
    localStorage.setItem(ACCESS_KEY, 'access-1')
    setSessionRole('viewer')
    globalThis.fetch = vi.fn().mockResolvedValue(jsonRes({ detail: 'Forbidden' }, 403))

    await expect(api.saveWorkflowCode('wf', 'code')).rejects.toThrow(/viewer/)
  })

  it('falls back to the plain message when the role is unknown', async () => {
    localStorage.setItem(ACCESS_KEY, 'access-1')
    globalThis.fetch = vi.fn().mockResolvedValue(jsonRes({ detail: 'Forbidden' }, 403))

    await expect(api.saveWorkflowCode('wf', 'code')).rejects.toThrow('Forbidden')
  })
})
