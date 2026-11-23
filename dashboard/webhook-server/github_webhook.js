import crypto from 'crypto'

const GITHUB_SIGNATURE_HEADER = 'x-hub-signature-256'
const REPLAY_WINDOW_MS = 300_000 // 5 minutes

// Verify GitHub's HMAC signature on a webhook payload.
// Returns true if signature is valid, false if invalid or missing.
export function verifySignature(payload, signature, secret) {
  if (!signature || !secret) return false
  const hmac = crypto.createHmac('sha256', secret)
  hmac.update(payload)
  const expected = `sha256=${hmac.digest('hex')}`
  return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))
}

// Create a bounded replay-window store to prevent duplicate webhook deliveries.
// GitHub delivers each webhook with an X-GitHub-Delivery header; we reject duplicates
// within the window and forget them after.
export function createReplayWindow({ ttlMs = REPLAY_WINDOW_MS, now = Date.now } = {}) {
  const seen = new Map() // deliveryId -> timestamp
  return {
    has(deliveryId) {
      if (!seen.has(deliveryId)) return false
      const age = now() - seen.get(deliveryId)
      if (age >= ttlMs) {
        seen.delete(deliveryId)
        return false
      }
      return true
    },
    add(deliveryId) {
      seen.set(deliveryId, now())
    },
    // Cleanup: remove entries older than ttl
    cleanup() {
      const cutoff = now() - ttlMs
      for (const [id, ts] of seen.entries()) {
        if (ts < cutoff) seen.delete(id)
      }
    }
  }
}

// Extract the repo owner/name from a GitHub webhook payload (supports push and pull_request events).
export function extractRepo(payload) {
  if (!payload || typeof payload !== 'object') return null
  if (payload.repository && typeof payload.repository.full_name === 'string') {
    return payload.repository.full_name
  }
  return null
}

// Pure webhook handler: validate signature, check replay window, extract repo.
// Returns { ok: boolean, repo: string | null, error?: string }
export function handleGithubWebhook({
  body,
  signature,
  deliveryId,
  secret,
  replayWindow,
  now = Date.now
}) {
  if (!body || !signature || !deliveryId || !secret) {
    return { ok: false, repo: null, error: 'missing required headers or body' }
  }

  // Check replay window first (before expensive crypto)
  if (replayWindow.has(deliveryId)) {
    return { ok: false, repo: null, error: 'duplicate delivery' }
  }

  // Verify signature
  if (!verifySignature(body, signature, secret)) {
    return { ok: false, repo: null, error: 'invalid signature' }
  }

  // Parse payload
  let payload
  try {
    payload = JSON.parse(body)
  } catch {
    return { ok: false, repo: null, error: 'invalid JSON' }
  }

  // Extract repo
  const repo = extractRepo(payload)
  if (!repo) {
    return { ok: false, repo: null, error: 'could not extract repo' }
  }

  // Record in replay window
  replayWindow.add(deliveryId)

  return { ok: true, repo, error: null }
}
