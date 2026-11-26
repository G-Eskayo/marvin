import { describe, it, expect } from 'vitest'
import { createHmac } from 'crypto'
import { verifySignature, parseDelivery, createDeliveryDedup, loadWebhookSecret, isForwardedEvent } from '../webhook-server/github_webhook.js'

describe('verifySignature', () => {
  const secret = 'my-secret'
  const body = JSON.stringify({ action: 'opened', pull_request: { number: 1 } })
  const correctSignature = `sha256=${createHmac('sha256', secret).update(body).digest('hex')}`

  it('accepts a valid signature (Node header format: bare sha256=...)', () => {
    // This is what Node's req.headers['x-hub-signature-256'] provides (no header name prefix)
    expect(verifySignature(secret, body, correctSignature)).toBe(true)
  })

  it('rejects an invalid signature', () => {
    expect(verifySignature(secret, body, 'sha256=bad')).toBe(false)
  })

  it('rejects a missing header', () => {
    expect(verifySignature(secret, body, undefined)).toBe(false)
    expect(verifySignature(secret, body, '')).toBe(false)
  })

  it('rejects a signature with wrong algorithm', () => {
    expect(verifySignature(secret, body, 'sha1=bad')).toBe(false)
  })

  it('rejects the full HTTP header format (should be bare signature only)', () => {
    // This was the old bug: expecting full header format when Node gives bare value
    const fullHeader = `X-Hub-Signature-256: ${correctSignature}`
    expect(verifySignature(secret, body, fullHeader)).toBe(false)
  })

  it('is timing-safe: compares signatures without early return on length mismatch', () => {
    // Both an invalid short signature and an invalid long signature should be compared
    // using timingSafeEqual, not early-returned. The function rejects based on signature
    // length being != 64 (after parsing), not based on comparing the full header first.
    const shortSig = 'sha256=' + 'a'.repeat(32) // 32-char hex, should fail length check
    const wrongSig = 'sha256=' + 'a'.repeat(64) // 64-char hex, passes length, fails comparison
    // Both should return false, but the second one goes through timingSafeEqual
    expect(verifySignature(secret, body, shortSig)).toBe(false)
    expect(verifySignature(secret, body, wrongSig)).toBe(false)
  })

  it('checks header length before regex to avoid ReDoS on huge payloads', () => {
    // A header that is longer than the 256-byte check should be rejected immediately,
    // before regex matching. This prevents ReDoS on a header like:
    // 'sha256=' + 'a'.repeat(1_000_000) which could cause excessive backtracking.
    const hugeHeader = 'sha256=' + 'a'.repeat(1000)
    expect(hugeHeader.length).toBeGreaterThan(256)
    const result = verifySignature(secret, body, hugeHeader)
    expect(result).toBe(false)
  })
})

describe('parseDelivery', () => {
  const deliveryId = '12345-67890'

  it('parses a valid GitHub webhook delivery from pull_request event', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'pull_request' }
    const body = JSON.stringify({ action: 'opened', repository: { full_name: 'owner/repo' } })
    const result = parseDelivery(headers, body)
    expect(result).toEqual({ event: 'pull_request', deliveryId, repo: 'owner/repo' })
  })

  it('parses delivery from issues event (no pull_request field)', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'issues' }
    const body = JSON.stringify({ action: 'opened', repository: { full_name: 'owner/repo' } })
    const result = parseDelivery(headers, body)
    expect(result).toEqual({ event: 'issues', deliveryId, repo: 'owner/repo' })
  })

  it('parses delivery from push event (no pull_request field)', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'push' }
    const body = JSON.stringify({ ref: 'refs/heads/main', repository: { full_name: 'owner/repo' } })
    const result = parseDelivery(headers, body)
    expect(result).toEqual({ event: 'push', deliveryId, repo: 'owner/repo' })
  })

  it('parses delivery from issue_comment event', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'issue_comment' }
    const body = JSON.stringify({ action: 'created', issue: { number: 42 }, repository: { full_name: 'owner/repo' } })
    const result = parseDelivery(headers, body)
    expect(result).toEqual({ event: 'issue_comment', deliveryId, repo: 'owner/repo' })
  })

  it('parses delivery from pull_request_review event', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'pull_request_review' }
    const body = JSON.stringify({ action: 'submitted', review: { state: 'approved' }, repository: { full_name: 'owner/repo' } })
    const result = parseDelivery(headers, body)
    expect(result).toEqual({ event: 'pull_request_review', deliveryId, repo: 'owner/repo' })
  })

  it('handles repos with hyphens and underscores in names', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'pull_request' }
    const body = JSON.stringify({ repository: { full_name: 'owner/repo-name_test' } })
    const result = parseDelivery(headers, body)
    expect(result.repo).toBe('owner/repo-name_test')
  })

  it('returns null on malformed JSON', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'pull_request' }
    expect(parseDelivery(headers, 'not json')).toBeNull()
  })

  it('returns null on missing deliveryId', () => {
    const body = JSON.stringify({ repository: { full_name: 'owner/repo' } })
    expect(parseDelivery({}, body)).toBeNull()
    expect(parseDelivery({ 'x-github-event': 'pull_request' }, body)).toBeNull()
  })

  it('returns null on missing event header', () => {
    const body = JSON.stringify({ repository: { full_name: 'owner/repo' } })
    expect(parseDelivery({ 'x-github-delivery': deliveryId }, body)).toBeNull()
  })

  it('returns null on missing repository.full_name in body', () => {
    const headers = { 'x-github-delivery': deliveryId, 'x-github-event': 'pull_request' }
    const body = JSON.stringify({ action: 'opened' })
    expect(parseDelivery(headers, body)).toBeNull()
  })
})

describe('createDeliveryDedup', () => {
  it('tracks seen delivery IDs', () => {
    const dedup = createDeliveryDedup({ cap: 100 })
    expect(dedup.seen('id-1')).toBe(false)
    expect(dedup.seen('id-1')).toBe(true)
    expect(dedup.seen('id-2')).toBe(false)
  })

  it('evicts oldest entries when cap is reached', () => {
    const dedup = createDeliveryDedup({ cap: 2 })
    // Add 3 items to a cap-2 cache
    expect(dedup.seen('old')).toBe(false)
    expect(dedup.seen('recent1')).toBe(false)
    expect(dedup.seen('recent2')).toBe(false)
    // 'old' should be evicted, only recent1 and recent2 remain
    expect(dedup.seen('old')).toBe(false)
    expect(dedup.seen('recent1')).toBe(true)
    expect(dedup.seen('recent2')).toBe(true)
  })

  it('stays bounded: evicted IDs are not re-tracked', () => {
    const dedup = createDeliveryDedup({ cap: 3 })
    // Add 10 items to a cap-3 cache, verify no unbounded growth
    for (let i = 0; i < 10; i++) {
      dedup.seen(`id-${i}`)
    }
    // The oldest items (id-0, id-1, ..., id-6) should all be evicted
    // Only id-7, id-8, id-9 should be tracked
    expect(dedup.seen('id-7')).toBe(true)
    expect(dedup.seen('id-8')).toBe(true)
    expect(dedup.seen('id-9')).toBe(true)
    // Evicted items should return false (not re-track them)
    expect(dedup.seen('id-0')).toBe(false)
    expect(dedup.seen('id-6')).toBe(false)
  })

  it('handles cap of 0 (no dedup)', () => {
    const dedup = createDeliveryDedup({ cap: 0 })
    expect(dedup.seen('id-1')).toBe(false)
    expect(dedup.seen('id-1')).toBe(false)
  })

  it('handles cap of 1', () => {
    const dedup = createDeliveryDedup({ cap: 1 })
    expect(dedup.seen('id-1')).toBe(false)
    expect(dedup.seen('id-1')).toBe(true)
    expect(dedup.seen('id-2')).toBe(false)
    expect(dedup.seen('id-1')).toBe(false)
  })
})

describe('loadWebhookSecret', () => {
  it('reads the secret from a file', () => {
    const read = (p) => {
      if (p.includes('.webhook-secret')) return 'my-webhook-secret\n'
      throw new Error('no file')
    }
    const secret = loadWebhookSecret({}, '/home/user', read)
    expect(secret).toBe('my-webhook-secret')
  })

  it('trims whitespace', () => {
    const read = (p) => '  secret-with-spaces  \n'
    const secret = loadWebhookSecret({}, '/home/user', read)
    expect(secret).toBe('secret-with-spaces')
  })

  it('returns empty string if file is missing', () => {
    const read = (p) => { throw new Error('no file') }
    const secret = loadWebhookSecret({}, '/home/user', read)
    expect(secret).toBe('')
  })

  it('uses home directory to build the path', () => {
    let readPath = null
    const read = (p) => { readPath = p; return 'secret' }
    loadWebhookSecret({}, '/Users/developer', read)
    expect(readPath).toContain('/Users/developer')
    expect(readPath).toContain('.webhook-secret')
  })
})

describe('isForwardedEvent', () => {
  it('allows the five whitelisted events', () => {
    const allowed = ['pull_request', 'pull_request_review', 'issues', 'issue_comment', 'push']
    for (const event of allowed) {
      expect(isForwardedEvent(event)).toBe(true)
    }
  })

  it('rejects other events', () => {
    const rejected = ['check_run', 'check_suite', 'workflow_run', 'pull_request_review_comment', 'unknown']
    for (const event of rejected) {
      expect(isForwardedEvent(event)).toBe(false)
    }
  })

  it('handles null and undefined', () => {
    expect(isForwardedEvent(null)).toBe(false)
    expect(isForwardedEvent(undefined)).toBe(false)
  })
})
