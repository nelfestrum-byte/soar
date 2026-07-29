import { reactive } from 'vue'

export const toasts = reactive([])

let nextId = 1

function push(kind, message, ttl) {
  const id = nextId++
  toasts.push({ id, kind, message })
  if (ttl) setTimeout(() => dismiss(id), ttl)
  return id
}

export function dismiss(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i !== -1) toasts.splice(i, 1)
}

export const notify = {
  // errors stay until dismissed — an operator who looked away should still see the failure
  error: (message) => push('error', message, 0),
  success: (message) => push('success', message, 4000),
  info: (message) => push('info', message, 4000),
}
