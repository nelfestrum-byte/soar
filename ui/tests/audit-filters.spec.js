import { describe, expect, it } from 'vitest'
import { RESOURCE_TYPES, presetRange } from '../src/audit-filters.js'

describe('RESOURCE_TYPES', () => {
  // grep -rhoE 'resource_type="[a-z_]+"' orchestrator/ — all 8 the backend writes
  it('lists every resource type the backend writes to the audit log', () => {
    expect(RESOURCE_TYPES.sort()).toEqual(
      ['action', 'apikey', 'connector', 'job', 'prompt', 'transfer', 'user', 'workflow'].sort()
    )
  })
})

describe('presetRange', () => {
  const now = new Date('2026-07-29T12:00:00.000Z')

  it('computes the last hour', () => {
    const { since, until } = presetRange('hour', now)
    expect(until).toBe('2026-07-29T12:00:00.000Z')
    expect(since).toBe('2026-07-29T11:00:00.000Z')
  })

  it('computes the last day', () => {
    const { since, until } = presetRange('day', now)
    expect(since).toBe('2026-07-28T12:00:00.000Z')
    expect(until).toBe('2026-07-29T12:00:00.000Z')
  })

  it('computes the last week', () => {
    const { since, until } = presetRange('week', now)
    expect(since).toBe('2026-07-22T12:00:00.000Z')
    expect(until).toBe('2026-07-29T12:00:00.000Z')
  })

  it('returns null bounds for an unknown preset', () => {
    expect(presetRange('decade', now)).toEqual({ since: null, until: null })
  })
})
