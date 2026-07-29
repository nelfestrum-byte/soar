import { describe, expect, it } from 'vitest'
import { HISTORY_PATHS } from '../src/history-paths.js'

describe('HISTORY_PATHS', () => {
  // orchestrator/api/workflows.py:211 — /{name}/code/history
  it('resolves workflow code under /workflows/{name}/code', () => {
    expect(HISTORY_PATHS.workflow('enrich_ip')).toBe('/workflows/enrich_ip/code')
  })

  // orchestrator/api/actions.py:116 — /{name}/history, no /code segment
  it('resolves action under /actions/{name} without a /code segment', () => {
    expect(HISTORY_PATHS.action('block_ip')).toBe('/actions/block_ip')
  })

  // orchestrator/api/connectors.py:470 — /{name}/code/history
  it('resolves connector code under /connectors/{name}/code', () => {
    expect(HISTORY_PATHS.connector_code('virus_total')).toBe('/connectors/virus_total/code')
  })

  // orchestrator/api/connectors.py:578 — /{name}/config/history
  it('resolves connector config under /connectors/{name}/config', () => {
    expect(HISTORY_PATHS.connector_config('virus_total')).toBe('/connectors/virus_total/config')
  })
})
