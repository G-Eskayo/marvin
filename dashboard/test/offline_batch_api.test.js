import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createOfflineBatchApiRouter } from '../mobile-backend/offline_batch_api.js'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

// Create a mock request object with method, url, headers, and optional body data
class MockRequest {
  constructor(method, url, body) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost' }
    this.body = body
  }

  // Make it async iterable for reading body chunks
  async *[Symbol.asyncIterator]() {
    if (this.body) {
      yield Buffer.from(this.body)
    }
  }
}

// Create a mock response object that captures writeHead and write calls
class MockResponse {
  constructor() {
    this.statusCode = null
    this.headers = {}
    this.chunks = []
    this.ended = false
  }

  writeHead(statusCode, headers = {}) {
    this.statusCode = statusCode
    this.headers = headers
    return this
  }

  write(chunk) {
    if (typeof chunk === 'string') {
      this.chunks.push(chunk)
    } else {
      this.chunks.push(chunk.toString())
    }
  }

  end(chunk) {
    if (chunk !== undefined) {
      this.write(chunk)
    }
    this.ended = true
  }

  getBody() {
    return this.chunks.join('')
  }
}

// Mock runSession that yields predictable events
function createMockRunSession() {
  return async function* mockRunSession({ message, sessionId }) {
    yield {
      type: 'session',
      sessionId: sessionId || 'mock-sess-001'
    }
    yield {
      type: 'text',
      text: `Reviewed: ${message.substring(0, 50)}...`
    }
    yield {
      type: 'result',
      text: `Reviewed: ${message.substring(0, 50)}...`,
      sessionId: sessionId || 'mock-sess-001',
      costUsd: 0.001,
      durationMs: 100,
      isError: false
    }
  }
}

describe('offline_batch_api', () => {
  let tempDir, threadStore

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), 'offline-batch-api-test-'))
    threadStore = createThreadStore({ path: path.join(tempDir, 'thread.json') })
  })

  afterEach(async () => {
    await rm(tempDir, { recursive: true, force: true })
  })

  describe('POST /offline-batch', () => {
    it('accepts and appends offline exchanges', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'offline-1', role: 'user', text: 'hello offline', ts: 1000 },
          { clientId: 'offline-2', role: 'assistant', text: 'hi there', ts: 2000 }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)

      const response = JSON.parse(res.getBody())
      expect(response.ok).toBe(true)
      expect(response.data.added).toHaveLength(2)
      expect(response.data.skipped).toHaveLength(0)
      expect(response.data.reviewed).toBe(true)
    })

    it('marks exchanges with offline source', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'offline-1', role: 'user', text: 'test', ts: 1000 }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      expect(state.messages).toHaveLength(1)
      expect(state.messages[0].source).toBe('offline')
    })

    it('stores clientId on each message', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'client-x', role: 'user', text: 'msg1', ts: 1000 }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      expect(state.messages[0].clientId).toBe('client-x')
    })

    it('deduplicates by clientId (AC1)', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'dup-1', role: 'user', text: 'first', ts: 1000 },
          { clientId: 'dup-2', role: 'assistant', text: 'second', ts: 2000 }
        ]
      }

      // First batch
      const req1 = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res1 = new MockResponse()
      await router(req1, res1)

      const resp1 = JSON.parse(res1.getBody())
      expect(resp1.data.added).toHaveLength(2)
      expect(resp1.data.skipped).toHaveLength(0)

      // Identical batch (retry)
      const req2 = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res2 = new MockResponse()
      await router(req2, res2)

      const resp2 = JSON.parse(res2.getBody())
      expect(resp2.data.added).toHaveLength(0)
      expect(resp2.data.skipped).toHaveLength(2)
      expect(resp2.data.reviewed).toBe(false)
    })

    it('partial dedup: skips known clientIds, appends new ones', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      // First batch: add two messages
      const payload1 = {
        exchanges: [
          { clientId: 'dup-1', role: 'user', text: 'msg1', ts: 1000 },
          { clientId: 'dup-2', role: 'user', text: 'msg2', ts: 2000 }
        ]
      }
      const req1 = new MockRequest('POST', '/offline-batch', JSON.stringify(payload1))
      const res1 = new MockResponse()
      await router(req1, res1)

      // Second batch: 1 already seen, 2 new
      const payload2 = {
        exchanges: [
          { clientId: 'dup-1', role: 'user', text: 'msg1', ts: 1000 },
          { clientId: 'new-1', role: 'user', text: 'msg3', ts: 3000 },
          { clientId: 'new-2', role: 'assistant', text: 'msg4', ts: 4000 }
        ]
      }
      const req2 = new MockRequest('POST', '/offline-batch', JSON.stringify(payload2))
      const res2 = new MockResponse()
      await router(req2, res2)

      const resp2 = JSON.parse(res2.getBody())
      expect(resp2.data.added).toHaveLength(2)
      expect(resp2.data.skipped).toHaveLength(1)
      expect(resp2.data.skipped[0]).toBe('dup-1')
    })

    it('invokes runSession with review prompt', async () => {
      let capturedMessage = null
      const mockRunSession = async function* (opts) {
        capturedMessage = opts.message
        yield* createMockRunSession()(opts)
      }

      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: mockRunSession
      })

      const payload = {
        exchanges: [
          { clientId: 'offline-1', role: 'user', text: 'test message', ts: 1000 }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      await router(req, res)

      expect(capturedMessage).toContain('Review and curate')
      expect(capturedMessage).toContain('test message')
    })

    it('backfills sessionId on newly-added messages from review result', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'offline-1', role: 'user', text: 'msg', ts: 1000 }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      expect(state.messages[0].sessionId).toBe('mock-sess-001')
    })

    it('sets current session after review', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'offline-1', role: 'user', text: 'msg', ts: 1000 }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      await router(req, res)

      expect(threadStore.currentSession()).toBe('mock-sess-001')
    })

    it('uses provided ts if given, otherwise uses current time', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const customTs = 1609459200000 // 2021-01-01
      const payload = {
        exchanges: [
          { clientId: 'offline-1', role: 'user', text: 'msg1', ts: customTs },
          { clientId: 'offline-2', role: 'user', text: 'msg2' } // no ts provided
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      const beforeTime = Date.now()
      await router(req, res)
      const afterTime = Date.now()

      const state = threadStore.getState()
      expect(state.messages[0].ts).toBe(customTs)
      expect(state.messages[1].ts).toBeGreaterThanOrEqual(beforeTime)
      expect(state.messages[1].ts).toBeLessThanOrEqual(afterTime)
    })

    it('rejects empty exchanges array', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = { exchanges: [] }
      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('cannot be empty')
    })

    it('rejects exchanges that is not an array', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = { exchanges: 'not an array' }
      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('must be an array')
    })

    it('rejects exchange missing clientId', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { role: 'user', text: 'msg' } // missing clientId
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('clientId')
    })

    it('rejects exchange with invalid role', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'id1', role: 'invalid', text: 'msg' }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('role')
    })

    it('rejects exchange missing text', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const payload = {
        exchanges: [
          { clientId: 'id1', role: 'user' } // missing text
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('text')
    })

    it('rejects invalid JSON body', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/offline-batch', 'not valid json')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('Invalid JSON')
    })

    it('returns immediately with reviewed=false if all exchanges are duplicates', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      // First batch
      const payload = {
        exchanges: [
          { clientId: 'dup-1', role: 'user', text: 'msg1', ts: 1000 }
        ]
      }
      const req1 = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res1 = new MockResponse()
      await router(req1, res1)

      // Retry same batch
      const req2 = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res2 = new MockResponse()
      await router(req2, res2)

      const resp2 = JSON.parse(res2.getBody())
      expect(resp2.data.reviewed).toBe(false)
      // Thread should only have 1 message (from first batch)
      expect(threadStore.getState().messages).toHaveLength(1)
    })

    it('resumes with existing session if present', async () => {
      let capturedSessionId = null
      const mockRunSession = async function* (opts) {
        capturedSessionId = opts.sessionId
        yield* createMockRunSession()(opts)
      }

      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: mockRunSession
      })

      // Set an existing session
      threadStore.setCurrentSession('existing-session-id')

      const payload = {
        exchanges: [
          { clientId: 'offline-1', role: 'user', text: 'msg', ts: 1000 }
        ]
      }

      const req = new MockRequest('POST', '/offline-batch', JSON.stringify(payload))
      const res = new MockResponse()

      await router(req, res)

      expect(capturedSessionId).toBe('existing-session-id')
    })
  })

  describe('routing', () => {
    it('returns false for non-/offline-batch routes', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('GET', '/unknown', null)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for GET requests to /offline-batch', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('GET', '/offline-batch', null)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for POST requests to other paths', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/different', JSON.stringify({ exchanges: [] }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
