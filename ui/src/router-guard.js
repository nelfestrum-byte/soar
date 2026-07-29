import { can } from './permissions.js'

// A route carrying meta.cap is reachable only by roles holding that capability.
// Hiding the nav link is not enough — the URL stays typeable.
export function routeAllowed(to, role) {
  if (!to || !to.meta || !to.meta.cap) return true
  return can(role, to.meta.cap)
}
