// vitest's jsdom environment does not expose localStorage (jsdom itself does —
// the environment drops it), and api.js keeps tokens there. In-memory stand-in
// with the same surface, installed only when the real thing is missing.

import { vi } from 'vitest'

class MemoryStorage {
  #data = new Map()

  get length() { return this.#data.size }
  key(i) { return [...this.#data.keys()][i] ?? null }
  getItem(k) { return this.#data.has(String(k)) ? this.#data.get(String(k)) : null }
  setItem(k, v) { this.#data.set(String(k), String(v)) }
  removeItem(k) { this.#data.delete(String(k)) }
  clear() { this.#data.clear() }
}

if (typeof globalThis.localStorage === 'undefined') {
  const storage = new MemoryStorage()
  globalThis.localStorage = storage
  if (typeof globalThis.window !== 'undefined') globalThis.window.localStorage = storage
}

// Real monaco-editor doesn't run predictably under jsdom (no Worker in some
// configs, no canvas for text measurement). Mock the editor API module with a
// minimal stub; CodeEditor.vue and its tests both import this same mocked
// module (tests via `import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'`
// and reading `monaco.editor.create.mock.results` for the created stub).
function createMonacoEditorStub(initialValue) {
  let value = initialValue ?? ''
  return {
    getValue: vi.fn(() => value),
    setValue: vi.fn((v) => { value = v }),
    onDidChangeModelContent: vi.fn(() => ({ dispose: vi.fn() })),
    updateOptions: vi.fn(),
    dispose: vi.fn(),
    layout: vi.fn(),
  }
}

vi.mock('monaco-editor/editor/editor.api', () => ({
  editor: {
    create: vi.fn((container, options) => createMonacoEditorStub(options?.value)),
  },
}))
