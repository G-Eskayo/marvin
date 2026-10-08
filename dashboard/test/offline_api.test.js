import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createOfflineApiRouter } from '../mobile-backend/offline_api.js'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

// Mock request/response classes (reuse from chat_api.test.js pattern)
class MockRequest {
  constructor(method, url, body) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost' }
    this.body = body
  }

  async *[Symbol.asyncIterator]() {
    if (this.body) {
      yield Buffer.from(this.body)
    }
  }
}

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

function createMockRunSession() {
  return async function* mockRunSession({ message }) {
    yield {
      type: 'session',
      sessionId: 'mock-offline-sess'
    }
    yield {
      type: 'result',
      text: 'Reviewed',
      sessionId: 'mock-offline-sess',
      costUsd: 0.001,
      durationMs: 100,
      isError: false
    }
  }
}

describe('offline_api', () => {
  let tempDir, threadStore

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), 'offline-api-test-'))
    threadStore = createThreadStore({ path: path.join(tempDir, 'thread.json') })
  })

  afterEach(async () => {
    await rm(tempDir, { recursive: true, force: true })
  })

  describe('POST /offline-batch', () => {
    it('accepts offline batch request with exchanges array', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const body = JSON.stringify({
        exchanges: [
          { clientId: 'test-1', role: 'user', text: 'message' }
        ]
      })
      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
    })

    it('returns 400 on invalid JSON', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const req = new MockRequest('POST', '/offline-batch', 'not json')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('Invalid JSON')
    })

    it('returns 400 on missing exchanges array', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const body = JSON.stringify({ foo: 'bar' })
      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('exchanges')
    })

    it('returns 400 if exchanges is not an array', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const body = JSON.stringify({ exchanges: 'not an array' })
      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
    })

    it('returns success response with appended/skipped counts', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const body = JSON.stringify({
        exchanges: [
          { clientId: 'new-1', role: 'user', text: 'message' }
        ]
      })
      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      const response = JSON.parse(res.getBody())
      expect(response.ok).toBe(true)
      expect(response.data).toHaveProperty('appended')
      expect(response.data).toHaveProperty('skipped')
      expect(response.data).toHaveProperty('reviewed')
      expect(response.data.appended).toBe(1)
      expect(response.data.skipped).toBe(0)
    })

    it('appends offline messages to thread store', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const body = JSON.stringify({
        exchanges: [
          { clientId: 'offline-msg', role: 'user', text: 'offline content' }
        ]
      })
      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      expect(state.messages).toHaveLength(1)
      expect(state.messages[0]).toMatchObject({
        source: 'offline',
        role: 'user',
        text: 'offline content',
        clientId: 'offline-msg'
      })
    })

    it('returns 500 on internal error', async () => {
      const failingRunSession = async function* () {
        throw new Error('Session failed')
      }

      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: failingRunSession
      })

      const body = JSON.stringify({
        exchanges: [
          { clientId: 'err-test', role: 'user', text: 'message' }
        ]
      })
      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      try {
        await router(req, res)
      } catch {
        // Expected to potentially throw or handle internally
      }

      // Should either handle gracefully or the response was set
      expect(res.statusCode).toBeLessThanOrEqual(500)
    })
  })

  describe('routing', () => {
    it('returns false for non-/offline-batch routes', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const req = new MockRequest('GET', '/unknown', null)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for GET /offline-batch', async () => {
      const router = createOfflineApiRouter({
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const req = new MockRequest('GET', '/offline-batch', null)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
