import { describe, it, expect, vi } from 'vitest'
import { createHmac } from 'crypto'
import { handleGithubWebhookRequest, createDeliveryDeduplicator } from './github_webhook.js'

describe('github_webhook', () => {
  describe('handleGithubWebhookRequest', () => {
    const makeRequest = (overrides = {}) => {
      const baseBody = { repository: { full_name: 'test/repo' } }
      const body = typeof overrides.body === 'string' ? overrides.body : JSON.stringify({ ...baseBody, ...overrides.body })
      return {
        method: 'POST',
        url: '/github-webhook',
        headers: {
          'x-github-event': 'push',
          'x-github-delivery': 'test-delivery-id',
          'x-hub-signature-256': '',
          ...overrides.headers
        },
        body,
        ...overrides,
        body // override body again to ensure it's the right one
      }
    }

    const makeDeps = (overrides = {}) => ({
      watchedRepos: () => ['test/repo', 'other/repo'],
      isDeliveryDuplicate: () => false,
      recordDelivery: vi.fn(),
      refusal_log: { append: vi.fn() },
      ...overrides
    })

    it('rejects when no secret is configured', () => {
      const req = makeRequest()
      const deps = makeDeps()
      const { status, body } = handleGithubWebhookRequest(req, {
        onChange: vi.fn(),
        forwardToPeers: vi.fn(),
        deps,
        secret: null
      })
      expect(status).toBe(403)
      expect(JSON.parse(body).ok).toBe(false)
    })

    it('rejects when body is too large', () => {
      const secret = 'test-secret'
      const largeBody = 'x'.repeat(26 * 1024 * 1024)
      const sig = createHmac('sha256', secret).update(largeBody).digest('hex')
      const req = {
        method: 'POST',
        url: '/github-webhook',
        headers: {
          'x-github-event': 'push',
          'x-github-delivery': 'test-delivery-id',
          'x-hub-signature-256': `sha256=${sig}`
        },
        body: largeBody
      }
      const deps = makeDeps()
      const { status } = handleGithubWebhookRequest(req, {
        onChange: vi.fn(),
        forwardToPeers: vi.fn(),
        deps,
        secret
      })
      expect(status).toBe(413)
    })

    it('rejects when signature is invalid', () => {
      const secret = 'test-secret'
      const req = makeRequest({ headers: { 'x-hub-signature-256': 'sha256=wrong' } })
      const deps = makeDeps()
      const { status, body } = handleGithubWebhookRequest(req, {
        onChange: vi.fn(),
        forwardToPeers: vi.fn(),
        deps,
        secret
      })
      expect(status).toBe(403)
      expect(JSON.parse(body).error).toContain('signature')
    })

    it('rejects when body is invalid JSON', () => {
      const secret = 'test-secret'
      const body = 'not json'
      const sig = createHmac('sha256', secret).update(body).digest('hex')
      const req = makeRequest({ body, headers: { 'x-hub-signature-256': `sha256=${sig}` } })
      const deps = makeDeps()
      const { status } = handleGithubWebhookRequest(req, {
        onChange: vi.fn(),
        forwardToPeers: vi.fn(),
        deps,
        secret
      })
      expect(status).toBe(400)
    })

    it('rejects when repo is not in watched set', () => {
      const secret = 'test-secret'
      const body = JSON.stringify({ repository: { full_name: 'unknown/repo' } })
      const sig = createHmac('sha256', secret).update(body).digest('hex')
      const req = makeRequest({ body, headers: { 'x-hub-signature-256': `sha256=${sig}` } })
      const deps = makeDeps()
      const { status } = handleGithubWebhookRequest(req, {
        onChange: vi.fn(),
        forwardToPeers: vi.fn(),
        deps,
        secret
      })
      expect(status).toBe(403)
    })

    it('rejects duplicate deliveries', () => {
      const secret = 'test-secret'
      const body = JSON.stringify({ repository: { full_name: 'test/repo' } })
      const sig = createHmac('sha256', secret).update(body).digest('hex')
      const req = makeRequest({ body, headers: { 'x-hub-signature-256': `sha256=${sig}` } })
      const deps = makeDeps({ isDeliveryDuplicate: () => true })
      const { status, body: respBody } = handleGithubWebhookRequest(req, {
        onChange: vi.fn(),
        forwardToPeers: vi.fn(),
        deps,
        secret
      })
      expect(status).toBe(200)
      expect(JSON.parse(respBody).duplicate).toBe(true)
    })

    it('accepts valid webhook and calls onChange and forwardToPeers', () => {
      const secret = 'test-secret'
      const body = JSON.stringify({ repository: { full_name: 'test/repo' } })
      const sig = createHmac('sha256', secret).update(body).digest('hex')
      const req = {
        method: 'POST',
        url: '/github-webhook',
        headers: {
          'x-github-event': 'push',
          'x-github-delivery': 'test-delivery-id',
          'x-hub-signature-256': `sha256=${sig}`
        },
        body
      }
      const onChange = vi.fn()
      const forwardToPeers = vi.fn()
      const deps = makeDeps()
      const { status, body: respBody } = handleGithubWebhookRequest(req, {
        onChange,
        forwardToPeers,
        deps,
        secret
      })
      expect(status).toBe(200)
      expect(JSON.parse(respBody).ok).toBe(true)
      expect(onChange).toHaveBeenCalledWith('test/repo')
      expect(forwardToPeers).toHaveBeenCalledWith('test/repo')
      expect(deps.recordDelivery).toHaveBeenCalledWith('test-delivery-id')
    })
  })

  describe('createDeliveryDeduplicator', () => {
    it('tracks deliveries and reports duplicates', () => {
      const dup = createDeliveryDeduplicator(10)
      expect(dup.isDuplicate('id1')).toBe(false)
      dup.record('id1')
      expect(dup.isDuplicate('id1')).toBe(true)
      expect(dup.isDuplicate('id2')).toBe(false)
    })

    it('bounds the in-memory set size', () => {
      const dup = createDeliveryDeduplicator(5)
      for (let i = 0; i < 10; i++) {
        dup.record(`id${i}`)
      }
      // The first few should have been evicted
      expect(dup.isDuplicate('id0')).toBe(false)
      expect(dup.isDuplicate('id9')).toBe(true)
    })
  })
})
