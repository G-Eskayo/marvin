import { readFileSync } from 'fs'
import path from 'path'
import { createHmac, timingSafeEqual } from 'crypto'

const WEBHOOK_SECRET_FILE = '.webhook-secret'
const MAX_SIGNATURE_SIZE = 128
const ALLOWED_EVENTS = new Set(['pull_request', 'pull_request_review', 'issues', 'issue_comment', 'push'])

export function verifySignature(secret, rawBody, header) {
  if (!header || typeof header !== 'string') return false
  if (!secret || typeof secret !== 'string') return false
  if (typeof rawBody !== 'string') return false

  // Check length first to avoid timing leaks and ReDoS on huge payloads.
  if (header.length > 256) return false

  const match = header.match(/^sha256=([a-f0-9]+)$/i)
  if (!match) return false

  const signature = match[1]
  if (signature.length !== 64) return false

  // Timing-safe comparison.
  const expected = Buffer.from(createHmac('sha256', secret).update(rawBody).digest('hex'), 'utf8')
  const actual = Buffer.from(signature, 'utf8')

  try {
    return timingSafeEqual(expected, actual)
  } catch {
    return false
  }
}

export function parseDelivery(headers, rawBody) {
  if (typeof headers !== 'object' || !headers) return null
  const deliveryId = headers['x-github-delivery']
  const event = headers['x-github-event']
  if (typeof deliveryId !== 'string' || typeof event !== 'string') return null

  let parsed
  try {
    parsed = JSON.parse(rawBody)
  } catch {
    return null
  }

  const repo = parsed?.repository?.full_name
  if (typeof repo !== 'string') return null

  return { event, deliveryId, repo }
}

export function createDeliveryDedup({ cap = 1000 } = {}) {
  const seen = new Set()
  const evicted = new Set()
  return {
    seen(id) {
      if (seen.has(id)) return true
      // Once evicted, stay evicted (no re-adds).
      if (evicted.has(id)) return false
      // New ID: add it, and prune if over cap (evict oldest first entry added).
      if (cap > 0) {
        seen.add(id)
        while (seen.size > cap) {
          const oldest = seen.values().next().value
          seen.delete(oldest)
          evicted.add(oldest)
          // Keep evicted set bounded: when it exceeds 2x the cap, trim the oldest.
          if (evicted.size > cap * 2) {
            const oldestEvicted = evicted.values().next().value
            evicted.delete(oldestEvicted)
          }
        }
      }
      return false
    }
  }
}

export function loadWebhookSecret(env = process.env, home = process.env.HOME, read = (p) => readFileSync(p, 'utf8')) {
  try {
    const secret = String(read(path.join(home, '.claude', WEBHOOK_SECRET_FILE))).trim()
    return secret || ''
  } catch {
    return ''
  }
}

export function isForwardedEvent(event) {
  return typeof event === 'string' && ALLOWED_EVENTS.has(event)
}
