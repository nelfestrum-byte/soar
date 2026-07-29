// deploy/prod/nginx.conf and ui/vite.config.js both proxy /api/ straight onto
// the orchestrator with no further path rewrite server-side beyond stripping
// the /api prefix — so /api/webhooks/{name} is the real, externally callable
// URL, not just a UI convention.
export function webhookUrl(origin, name) {
  return `${origin}/api/webhooks/${name}`
}

// orchestrator/api/webhooks.py:28 — token compared via secrets.compare_digest
// against the X-Webhook-Token header
export function webhookCurl(origin, name, token) {
  const url = webhookUrl(origin, name)
  return `curl -X POST '${url}' \\\n  -H 'X-Webhook-Token: ${token}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{}'`
}
