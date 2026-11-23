import { verifyWebhookSignature } from './github_webhook_secret.js'

// marvin#566: handle incoming GitHub webhooks from Tailscale Funnel (/github-webhook path).
// Verifies signature, dedupes by X-GitHub-Delivery, calls onChange and forwardToPeers without awaiting.
// Logs refusals (forged, duplicate, out-of-scope repo) to github-webhook-refusals.jsonl via refusal_log pattern.

const BODY_SIZE_LIMIT = 25 * 1024 * 1024 // GitHub webhook payloads are typically <5 MB
const DELIVERY_DEDUP_MAX = 1000 // bounded in-memory set for recent deliveries

export function handleGithubWebhookRequest({ method, url, headers, body }, { deps, onChange, forwardToPeers, secret }) {
  const signature = headers['x-hub-signature-256'] || ''
  const delivery = headers['x-github-delivery'] || ''
  const event = headers['x-github-event'] || 'unknown'

  // Reject if no secret is loaded (fail closed on missing configuration).
  if (!secret) {
    recordRefusal({ delivery, event, reason: 'no webhook secret configured' }, deps)
    return { status: 403, body: JSON.stringify({ ok: false, error: 'webhook not configured' }) }
  }

  // Reject if body is too large.
  if (typeof body === 'string' && body.length > BODY_SIZE_LIMIT) {
    recordRefusal({ delivery, event, reason: 'body too large' }, deps)
    return { status: 413, body: JSON.stringify({ ok: false, error: 'payload too large' }) }
  }

  // Verify signature (fail closed if forged or missing).
  if (!verifyWebhookSignature(secret, body, signature)) {
    recordRefusal({ delivery, event, reason: 'invalid signature' }, deps)
    return { status: 403, body: JSON.stringify({ ok: false, error: 'invalid signature' }) }
  }

  // Parse JSON (fail closed on parse error).
  let payload
  try {
    payload = JSON.parse(body)
  } catch {
    recordRefusal({ delivery, event, reason: 'invalid json' }, deps)
    return { status: 400, body: JSON.stringify({ ok: false, error: 'invalid json' }) }
  }

  // Dedupe by X-GitHub-Delivery.
  if (deps.isDeliveryDuplicate(delivery)) {
    recordRefusal({ delivery, event, reason: 'duplicate delivery' }, deps)
    return { status: 200, body: JSON.stringify({ ok: true, duplicate: true }) }
  }

  // Check repo is in watched set.
  const repo = payload.repository?.full_name || ''
  if (!repo || !deps.watchedRepos().includes(repo)) {
    recordRefusal({ delivery, event, reason: `unknown repo: ${repo}` }, deps)
    return { status: 403, body: JSON.stringify({ ok: false, error: 'repo not in scope' }) }
  }

  // Record the delivery as seen.
  deps.recordDelivery(delivery)

  // Fire onChange and forwardToPeers without awaiting; respond at once.
  onChange(repo)
  forwardToPeers(repo)

  return { status: 200, body: JSON.stringify({ ok: true }) }
}

// Create a deduplication tracker for X-GitHub-Delivery IDs, bounded in memory.
export function createDeliveryDeduplicator(maxSize = DELIVERY_DEDUP_MAX) {
  const seen = new Map() // delivery id -> timestamp
  return {
    isDuplicate: (id) => seen.has(id),
    record: (id) => {
      seen.set(id, Date.now())
      // Trim old entries if the map grows large (keep only the most recent).
      if (seen.size > maxSize) {
        const sorted = Array.from(seen.entries()).sort((a, b) => a[1] - b[1])
        for (let i = 0; i < sorted.length - maxSize; i++) seen.delete(sorted[i][0])
      }
    }
  }
}

function recordRefusal({ delivery, event, reason }, { refusal_log = null }) {
  if (!refusal_log) return
  try {
    refusal_log.append(JSON.stringify({ t: new Date().toISOString(), kind: 'webhook-refusal', delivery, event, reason }) + '\n')
  } catch { /* fail-soft */ }
}
