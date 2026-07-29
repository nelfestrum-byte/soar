// Mirror of the role tuples in orchestrator/api/*.py. A capability listed here
// must match the roles the corresponding route accepts — when a tuple changes
// on the backend, this table changes with it, or the UI starts offering
// actions that end in 403.

export const ROLES = ['viewer', 'analyst', 'service', 'admin', 'agent']

const CAPS = {
  // workflows.py:20, actions.py:23 — _ADMIN
  'code.write': ['admin', 'agent'],
  // connectors.py:516 — literal ("admin",) since BAGFIX B3
  'connector.code.write': ['admin'],
  // connectors.py:628 — _ADMIN; hidden fields inside are admin-only
  'connector.config.write': ['admin', 'agent'],
  // connectors.py:339,668,717 — _ADMIN
  'connector.manage': ['admin', 'agent'],
  // logs.py:13 — _RW
  'logs.read': ['analyst', 'service', 'admin', 'agent'],
  // jobs.py:14 — _RW
  'job.create': ['analyst', 'service', 'admin', 'agent'],
  // jobs.py:15 — _ANALYST
  'job.cancel': ['analyst', 'admin', 'agent'],
  // workflows.py:19 — _RW
  'workflow.reload': ['analyst', 'admin', 'agent'],
  // workflows.py:125,146 — _RW
  'workflow.toggle': ['analyst', 'admin', 'agent'],
  // connectors.py:30 — _RW
  'connector.preview': ['analyst', 'admin', 'agent'],
  // */{name}/**/restore — _ADMIN
  'restore': ['admin', 'agent'],
  // prompts.py:13 — _ADMIN
  'prompt.write': ['admin'],
  // transfer.py:24 — router-wide require_role("admin")
  'transfer': ['admin'],
  // audit.py:30
  'audit.read': ['admin'],
  // auth/router.py — users and keys
  'auth.admin': ['admin'],
}

export function can(role, cap) {
  return (CAPS[cap] || []).includes(role)
}
