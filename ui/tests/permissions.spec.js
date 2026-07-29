import { describe, expect, it } from 'vitest'
import { ROLES, can } from '../src/permissions.js'

describe('ROLES', () => {
  it('lists every role the backend accepts', () => {
    expect(ROLES).toEqual(['viewer', 'analyst', 'service', 'admin', 'agent'])
  })
})

describe('can()', () => {
  it('grants admin everything', () => {
    const caps = [
      'code.write', 'connector.code.write', 'connector.config.write',
      'logs.read', 'job.create', 'job.cancel', 'workflow.reload',
      'workflow.toggle', 'restore', 'prompt.write', 'transfer', 'audit.read', 'auth.admin',
    ]
    for (const cap of caps) expect(can('admin', cap), cap).toBe(true)
  })

  it('grants viewer nothing but reading', () => {
    const caps = [
      'code.write', 'connector.code.write', 'connector.config.write',
      'logs.read', 'job.create', 'job.cancel', 'workflow.reload',
      'workflow.toggle', 'restore', 'prompt.write', 'transfer', 'audit.read', 'auth.admin',
    ]
    for (const cap of caps) expect(can('viewer', cap), cap).toBe(false)
  })

  // orchestrator/api/logs.py:13 — _RW excludes viewer
  it('denies viewer the job log', () => {
    expect(can('viewer', 'logs.read')).toBe(false)
    expect(can('analyst', 'logs.read')).toBe(true)
    expect(can('service', 'logs.read')).toBe(true)
    expect(can('agent', 'logs.read')).toBe(true)
  })

  // UPGRADE.md stage 3 + BAGFIX_PLAN B3 — agent writes code, administers nothing
  it('keeps agent out of administration', () => {
    expect(can('agent', 'code.write')).toBe(true)
    expect(can('agent', 'job.create')).toBe(true)
    expect(can('agent', 'restore')).toBe(true)

    expect(can('agent', 'connector.code.write')).toBe(false)
    expect(can('agent', 'prompt.write')).toBe(false)
    expect(can('agent', 'transfer')).toBe(false)
    expect(can('agent', 'audit.read')).toBe(false)
    expect(can('agent', 'auth.admin')).toBe(false)
  })

  // orchestrator/api/connectors.py:516 — literal ("admin",) after B3
  it('lets only admin write connector code', () => {
    expect(can('admin', 'connector.code.write')).toBe(true)
    for (const role of ['viewer', 'analyst', 'service', 'agent']) {
      expect(can(role, 'connector.code.write'), role).toBe(false)
    }
  })

  // orchestrator/api/jobs.py:14-15 — service may create a job but not cancel one
  it('separates job.create from job.cancel for service', () => {
    expect(can('service', 'job.create')).toBe(true)
    expect(can('service', 'job.cancel')).toBe(false)
  })

  // orchestrator/api/workflows.py:19 — _RW excludes service
  it('denies service the workflow reload', () => {
    expect(can('service', 'workflow.reload')).toBe(false)
    expect(can('analyst', 'workflow.reload')).toBe(true)
  })

  it('grants analyst run-and-read but no writing', () => {
    expect(can('analyst', 'job.create')).toBe(true)
    expect(can('analyst', 'job.cancel')).toBe(true)
    expect(can('analyst', 'logs.read')).toBe(true)
    expect(can('analyst', 'connector.config.write')).toBe(false)
    expect(can('analyst', 'code.write')).toBe(false)
    expect(can('analyst', 'restore')).toBe(false)
  })

  it('returns false for an unknown capability or role', () => {
    expect(can('admin', 'nope.nope')).toBe(false)
    expect(can('root', 'code.write')).toBe(false)
    expect(can('', 'logs.read')).toBe(false)
    expect(can(undefined, 'logs.read')).toBe(false)
  })
})
