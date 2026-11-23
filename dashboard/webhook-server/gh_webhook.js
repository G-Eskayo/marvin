import crypto from 'crypto'

// HMAC-SHA256 signature verification for GitHub webhooks. Timing-safe to prevent timing attacks.
export function verifySignature(secret, rawBody, header = '') {
  if (!secret) return false
  if (typeof rawBody !== 'string') return false
  const headerValue = String(header).trim()
  if (!headerValue.startsWith('sha256=')) return false

  const signature = crypto.createHmac('sha256', secret).update(rawBody, 'utf8').digest('hex')
  const expected = `sha256=${signature}`

  // Constant-time comparison to prevent timing attacks. Length mismatch is handled safely.
  const expectedBuf = Buffer.from(expected)
  const headerBuf = Buffer.from(headerValue)
  if (expectedBuf.length !== headerBuf.length) return false
  return crypto.timingSafeEqual(expectedBuf, headerBuf).valueOf()
}

// Bounded in-memory dedup for webhook deliveries: prevents double-processing of retries
export function createDeliveryDedup(cap = 500) {
  const seen = new Set()
  return {
    seen: (deliveryId) => seen.has(deliveryId),
    record: (deliveryId) => {
      if (seen.size >= cap) {
        const first = seen.values().next().value
        seen.delete(first)
      }
      seen.add(deliveryId)
    }
  }
}

// Repository allowlist: only process changes from specified repos
export function repoAllowed(fullName, repos) {
  if (!fullName || !repos) return false
  return repos.includes(fullName)
}

// Pure handler for GitHub webhook events. Returns object with { status, json, repo, event, forward }
export function handleGithubWebhook(
  { headers = {}, rawBody = '', repos = [], secret = null },
  { dedup = null } = {}
) {
  const result = {
    status: 400,
    json: { ok: false, error: 'invalid request' },
    repo: null,
    event: null,
    forward: false
  }

  if (!secret) {
    result.status = 401
    result.json.error = 'webhook secret not configured'
    return result
  }

  // Verify signature
  const signatureHeader = headers['x-hub-signature-256'] || ''
  if (!verifySignature(secret, rawBody, signatureHeader)) {
    result.status = 401
    result.json.error = 'invalid signature'
    return result
  }

  // Parse body
  let body
  try {
    body = JSON.parse(rawBody)
  } catch {
    result.status = 400
    result.json.error = 'invalid json'
    return result
  }

  // Check delivery ID for dedup
  const deliveryId = headers['x-github-delivery'] || ''
  if (!deliveryId) {
    result.status = 400
    result.json.error = 'missing delivery id'
    return result
  }

  if (dedup?.seen(deliveryId)) {
    result.status = 202
    result.json = { ok: true, deduped: true }
    return result
  }

  // Extract repo and validate
  const repo = body.repository?.full_name || null
  if (!repo || !repoAllowed(repo, repos)) {
    result.status = 403
    result.json.error = 'repo not allowed'
    return result
  }

  // Extract event type
  const event = headers['x-github-event'] || null
  if (!event || typeof event !== 'string') {
    result.status = 400
    result.json.error = 'missing event type'
    return result
  }

  // Record successful delivery
  dedup?.record(deliveryId)

  result.status = 202
  result.json = { ok: true }
  result.repo = repo
  result.event = event
  result.forward = true

  return result
}
