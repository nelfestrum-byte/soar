import { describe, expect, it } from 'vitest'
import { webhookUrl, webhookCurl } from '../src/webhook.js'

describe('webhookUrl', () => {
  it('builds the URL under /api/webhooks/{name}', () => {
    expect(webhookUrl('http://localhost:3000', 'suspicious_login')).toBe(
      'http://localhost:3000/api/webhooks/suspicious_login'
    )
  })

  it('respects the origin the page was served from', () => {
    expect(webhookUrl('https://soar.example.com', 'phishing')).toBe(
      'https://soar.example.com/api/webhooks/phishing'
    )
  })
})

describe('webhookCurl', () => {
  // orchestrator/api/webhooks.py:28 — X-Webhook-Token, compared with secrets.compare_digest
  it('includes the token header and a JSON body', () => {
    const cmd = webhookCurl('http://localhost:3000', 'suspicious_login', 'tok_abc123')
    expect(cmd).toContain('X-Webhook-Token: tok_abc123')
    expect(cmd).toContain('http://localhost:3000/api/webhooks/suspicious_login')
    expect(cmd).toContain('-X POST')
  })
})
