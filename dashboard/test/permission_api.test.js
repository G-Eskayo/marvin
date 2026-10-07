import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createPermissionApiRouter } from '../mobile-backend/permission_api.js'
import { createPendingActionsStore } from '../mobile-backend/pending_actions.js'
import { mkdtempSync, rmSync } from 'fs'
import { join } from 'path'
import { tmpdir } from 'os'

class MockRequest {
  constructor(method, url, body = null) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost:7880' }
    this.body = body
    this.isStream = typeof body === 'object' && body !== null && Symbol.asyncIterator in body
  }

  async *[Symbol.asyncIterator]() {
    if (this.isStream) {
      yield* this.body
    } else if (this.body) {
      yield Buffer.from(this.body)
    }
  }
}

class MockResponse {
  constructor() {
    this.statusCode = null
    this.responseHeaders = null
    this.data = ''
    this.ended = false
  }

  writeHead(statusCode, headers) {
    this.statusCode = statusCode
    this.responseHeaders = headers
    return this
  }

  write(data) {
    this.data += data
  }

  end(data) {
    if (data) {
      this.data += data
    }
    this.ended = true
  }
}

describe('permission_api', () => {
  let testDir
  let filePath
  let store
  let router

  beforeEach(() => {
    testDir = mkdtempSync(join(tmpdir(), 'permission-api-test-'))
    filePath = join(testDir, 'pending-actions.json')
    store = createPendingActionsStore({ path: filePath })
    router = createPermissionApiRouter({ pendingActionStore: store })
  })

  afterEach(() => {
    rmSync(testDir, { recursive: true })
  })

  describe('GET /pending-actions', () => {
    it('returns empty list initially', async () => {
      const req = new MockRequest('GET', '/pending-actions')
      const res = new MockResponse()

      const handled = await router(req, res)

      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(true)
      expect(data.data).toEqual([])
    })

    it('returns list of pending actions', async () => {
      const action1 = store.create({
        toolName: 'Bash',
        toolInput: { command: 'test' },
        summary: 'Run test',
        sessionId: 'sess-123'
      })

      const action2 = store.create({
        toolName: 'Edit',
        toolInput: { file_path: 'test.js' },
        summary: 'Edit test.js',
        sessionId: 'sess-456'
      })

      const req = new MockRequest('GET', '/pending-actions')
      const res = new MockResponse()

      await router(req, res)

      const data = JSON.parse(res.data)
      expect(data.ok).toBe(true)
      expect(data.data).toHaveLength(2)
      expect(data.data[0].id).toBe(action1.id)
      expect(data.data[1].id).toBe(action2.id)
    })
  })

  describe('POST /pending-actions/resolve', () => {
    it('resolves an action to approved', async () => {
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      const body = JSON.stringify({ id: action.id, decision: 'allow' })
      const req = new MockRequest('POST', '/pending-actions/resolve', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(true)
      expect(data.data.status).toBe('approved')
      expect(data.data.decision).toBe('allow')
    })

    it('resolves an action to denied with reason', async () => {
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      const body = JSON.stringify({ id: action.id, decision: 'deny', reason: 'User rejected' })
      const req = new MockRequest('POST', '/pending-actions/resolve', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(true)
      expect(data.data.status).toBe('denied')
      expect(data.data.decision).toBe('deny')
      expect(data.data.reason).toBe('User rejected')
    })

    it('rejects invalid JSON', async () => {
      const req = new MockRequest('POST', '/pending-actions/resolve', 'not json')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(false)
      expect(data.error).toContain('Invalid JSON')
    })

    it('rejects missing id field', async () => {
      const body = JSON.stringify({ decision: 'allow' })
      const req = new MockRequest('POST', '/pending-actions/resolve', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(false)
      expect(data.error).toContain('Missing or invalid id')
    })

    it('rejects missing decision field', async () => {
      const body = JSON.stringify({ id: 'test-id' })
      const req = new MockRequest('POST', '/pending-actions/resolve', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(false)
      expect(data.error).toContain('Missing or invalid decision')
    })

    it('rejects invalid decision value', async () => {
      const body = JSON.stringify({ id: 'test-id', decision: 'maybe' })
      const req = new MockRequest('POST', '/pending-actions/resolve', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(false)
      expect(data.error).toContain('must be "allow" or "deny"')
    })

    it('rejects resolving non-existent action', async () => {
      const body = JSON.stringify({ id: 'non-existent-id', decision: 'allow' })
      const req = new MockRequest('POST', '/pending-actions/resolve', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(false)
      expect(data.error).toContain('Action not found')
    })

    it('rejects resolving already-resolved action', async () => {
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      store.resolve(action.id, 'allow')

      const body = JSON.stringify({ id: action.id, decision: 'deny' })
      const req = new MockRequest('POST', '/pending-actions/resolve', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
      const data = JSON.parse(res.data)
      expect(data.ok).toBe(false)
      expect(data.error).toContain('no longer pending')
    })
  })

  describe('unmatched routes', () => {
    it('returns false for unmatched routes', async () => {
      const req = new MockRequest('GET', '/unknown-path')
      const res = new MockResponse()

      const handled = await router(req, res)

      expect(handled).toBe(false)
    })
  })
})
