// vitest's jsdom environment does not expose localStorage (jsdom itself does —
// the environment drops it), and api.js keeps tokens there. In-memory stand-in
// with the same surface, installed only when the real thing is missing.

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
