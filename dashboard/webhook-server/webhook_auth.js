import { readFileSync } from 'fs'
import path from 'path'

// Export WEBHOOK_SECRET from ~/.claude/.gh-webhook-secret for HMAC verification of GitHub webhooks.
// Mirrors loadGhToken's pattern: reads once, never throws, returns null when absent.
// The secret is managed by lib/webhook_setup.py sync.
export function loadWebhookSecret(env = process.env, home = process.env.HOME, read = (p) => readFileSync(p, 'utf8')) {
  if (env.WEBHOOK_SECRET) return { source: 'env', secret: env.WEBHOOK_SECRET }
  try {
    const secret = String(read(path.join(home, '.claude', '.gh-webhook-secret'))).trim()
    if (secret) {
      env.WEBHOOK_SECRET = secret
      return { source: 'file', secret }
    }
  } catch {
    // missing/unreadable: webhook will not verify
  }
  return { source: 'none', secret: null }
}
