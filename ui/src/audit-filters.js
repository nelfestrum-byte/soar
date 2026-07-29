// Every resource_type orchestrator/audit/service.record() is called with —
// verified via grep -rhoE 'resource_type="[a-z_]+"' orchestrator/. `prompt`
// and `transfer` are the two BAGFIX_PLAN (S3/S4) additions the old hardcoded
// list in AuditLog.vue predated.
export const RESOURCE_TYPES = [
  'workflow', 'action', 'connector', 'apikey', 'job', 'prompt', 'transfer', 'user',
]

const PRESET_MS = {
  hour: 60 * 60 * 1000,
  day: 24 * 60 * 60 * 1000,
  week: 7 * 24 * 60 * 60 * 1000,
}

export function presetRange(preset, now = new Date()) {
  const ms = PRESET_MS[preset]
  if (!ms) return { since: null, until: null }
  return {
    since: new Date(now.getTime() - ms).toISOString(),
    until: now.toISOString(),
  }
}
