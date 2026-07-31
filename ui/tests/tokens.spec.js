import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative } from 'path'

const SRC = join(__dirname, '..', 'src')
const TOKENS_FILE = join(SRC, 'styles', 'tokens.css')

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (/\.(vue|js|css)$/.test(entry)) out.push(full)
  }
  return out
}

// (?<!&) excludes HTML numeric character references like &#10003; (a checkmark
// glyph, not a color) which otherwise look like a valid hex literal.
const HEX_COLOR = /(?<!&)#[0-9a-fA-F]{3,6}\b/g

describe('design tokens', () => {
  it('defines every semantic color and scale variable the app relies on', () => {
    const css = readFileSync(TOKENS_FILE, 'utf-8')
    const required = [
      '--color-surface', '--color-surface-alt', '--color-surface-dark', '--color-surface-hover',
      '--color-text', '--color-text-muted', '--color-text-faint', '--color-text-on-dark',
      '--color-border', '--color-border-subtle',
      '--color-accent', '--color-accent-fg', '--color-danger', '--color-success',
      '--color-result-ok', '--color-result-fail',
      '--status-pending-bg', '--status-pending-fg',
      '--status-running-bg', '--status-running-fg',
      '--status-completed-bg', '--status-completed-fg',
      '--status-failed-bg', '--status-failed-fg',
      '--status-cancelled-bg', '--status-cancelled-fg',
      '--status-timeout-bg', '--status-timeout-fg',
      '--space-1', '--space-2', '--space-3', '--space-4', '--space-5', '--space-6',
      '--space-7', '--space-8',
      '--radius-sm', '--radius', '--radius-md', '--radius-lg', '--radius-xl', '--radius-full',
      '--font-mono', '--font-sans',
      '--text-h1', '--text-h1-weight', '--text-h1-line', '--text-h1-tracking',
      '--text-h2', '--text-h2-weight', '--text-h2-line', '--text-h2-tracking',
      '--text-h3', '--text-h3-weight', '--text-h3-line',
      '--text-body', '--text-body-line',
      '--text-body-sm', '--text-body-sm-line',
      '--text-code', '--text-code-line',
      '--text-label-caps', '--text-label-caps-line', '--text-label-caps-tracking',
    ]
    for (const name of required) {
      expect(css, `missing ${name}`).toContain(`${name}:`)
    }
  })

  it('gives each of the six job statuses a distinct color, not four shared ones', () => {
    const css = readFileSync(TOKENS_FILE, 'utf-8')
    const statuses = ['pending', 'running', 'completed', 'failed', 'cancelled', 'timeout']
    const fgValues = statuses.map((status) => {
      const match = css.match(new RegExp(`--status-${status}-fg:\\s*([^;]+);`))
      if (!match) throw new Error(`--status-${status}-fg not found`)
      return match[1].trim()
    })
    expect(new Set(fgValues).size).toBe(6)
  })

  it('leaves no raw hex color literals outside tokens.css', () => {
    const offenders = []
    for (const file of walk(SRC)) {
      if (file === TOKENS_FILE) continue
      const text = readFileSync(file, 'utf-8')
      const matches = text.match(HEX_COLOR)
      if (matches) offenders.push(`${relative(SRC, file)}: ${matches.join(', ')}`)
    }
    expect(offenders, offenders.join('\n')).toEqual([])
  })
})
