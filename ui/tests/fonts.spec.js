import { describe, expect, it } from 'vitest'
import { readFileSync, existsSync } from 'fs'
import { join } from 'path'

const UI_ROOT = join(__dirname, '..')
const FONTS_CSS = join(UI_ROOT, 'src', 'styles', 'fonts.css')

const EXTERNAL_REF = /fonts\.googleapis\.com|url\(\s*['"]?https?:/i

describe('self-hosted fonts', () => {
  it('fonts.css exists and has no external font CDN references', () => {
    expect(existsSync(FONTS_CSS)).toBe(true)
    const css = readFileSync(FONTS_CSS, 'utf-8')
    expect(css).not.toMatch(EXTERNAL_REF)
  })

  it('main.js does not link an external font stylesheet', () => {
    const mainJs = readFileSync(join(UI_ROOT, 'src', 'main.js'), 'utf-8')
    expect(mainJs).not.toMatch(EXTERNAL_REF)
  })

  it('index.html does not link an external font stylesheet', () => {
    const indexHtml = readFileSync(join(UI_ROOT, 'index.html'), 'utf-8')
    expect(indexHtml).not.toMatch(EXTERNAL_REF)
  })
})
