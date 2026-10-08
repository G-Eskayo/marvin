import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createOfflineBatchApiRouter } from '../mobile-backend/offline_batch_api.js'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { createOfflineBatchStore } from '../mobile-backend/offline_batch_store.js'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

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
  return async function* mockRunSession({ exchanges }) {
    yield {
      type: 'session',
      sessionId: 'mock-review-sess-001'
    }
    yield {
      type: 'text',
      text: 'Reviewed batch'
    }
    yield {
      type: 'result',
      text: 'Reviewed batch',
      sessionId: 'mock-review-sess-001',
      costUsd: 0.001,
      durationMs: 100,
      isError: false
    }
  }
}

describe('offline_batch_api', () => {
  let tempDir, threadStore, offlineBatchStore

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), 'offline-batch-api-test-'))
    threadStore = createThreadStore({ path: path.join(tempDir, 'thread.json') })
    offlineBatchStore = createOfflineBatchStore({ path: path.join(tempDir, 'batches.json') })
  })

  afterEach(async () => {
    await rm(tempDir, { recursive: true, force: true })
  })

  describe('POST /offline-batch', () => {
    it('accepts valid request body', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-1',
        exchanges: [
          { role: 'user', text: 'hello' },
          { role: 'assistant', text: 'hi' }
        ]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
    })

    it('appends each exchange to thread store with source=offline', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-2',
        exchanges: [
          { role: 'user', text: 'question' },
          { role: 'assistant', text: 'answer' }
        ]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const offlineMessages = state.messages.filter(m => m.source === 'offline')
      expect(offlineMessages).toHaveLength(2)
      expect(offlineMessages[0].role).toBe('user')
      expect(offlineMessages[0].text).toBe('question')
      expect(offlineMessages[1].role).toBe('assistant')
      expect(offlineMessages[1].text).toBe('answer')
    })

    it('returns 200 with messageIds and sessionId', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-3',
        exchanges: [
          { role: 'user', text: 'test' }
        ]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      const response = JSON.parse(res.getBody())
      expect(response.ok).toBe(true)
      expect(response.data.batchId).toBe('batch-3')
      expect(Array.isArray(response.data.messageIds)).toBe(true)
      expect(response.data.messageIds).toHaveLength(1)
      expect(response.data.sessionId).toBe('mock-review-sess-001')
    })

    it('backfills sessionId onto all appended messages', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-4',
        exchanges: [
          { role: 'user', text: 'msg1' },
          { role: 'user', text: 'msg2' }
        ]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const offlineMessages = state.messages.filter(m => m.source === 'offline')
      for (const msg of offlineMessages) {
        expect(msg.sessionId).toBe('mock-review-sess-001')
      }
    })

    it('stores batch as complete in offline_batch_store', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-5',
        exchanges: [
          { role: 'user', text: 'test' }
        ]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      const batch = offlineBatchStore.get('batch-5')
      expect(batch.status).toBe('complete')
      expect(batch.sessionId).toBe('mock-review-sess-001')
    })

    it('is idempotent on replay: second request returns cached result', async () => {
      const mockRunSession = createMockRunSession()
      const runSessionSpy = vi.fn(mockRunSession)

      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: runSessionSpy
      })

      const body = JSON.stringify({
        batchId: 'batch-idempotent',
        exchanges: [
          { role: 'user', text: 'original' }
        ]
      })

      // First request
      const req1 = new MockRequest('POST', '/offline-batch', body)
      const res1 = new MockResponse()
      const handled1 = await router(req1, res1)
      expect(handled1).toBe(true)
      const response1 = JSON.parse(res1.getBody())
      const messageIds1 = response1.data.messageIds
      const runSessionCallCount1 = runSessionSpy.mock.calls.length

      // Second request with same batchId
      const req2 = new MockRequest('POST', '/offline-batch', body)
      const res2 = new MockResponse()
      await router(req2, res2)
      const response2 = JSON.parse(res2.getBody())

      // Should return same result
      expect(response2.data.batchId).toBe(response1.data.batchId)
      expect(response2.data.messageIds).toEqual(messageIds1)
      expect(response2.data.sessionId).toBe(response1.data.sessionId)

      // runSession should not be called again
      expect(runSessionSpy.mock.calls.length).toBe(runSessionCallCount1)

      // Thread should not have duplicate messages
      const state = threadStore.getState()
      const offlineMessages = state.messages.filter(m => m.source === 'offline')
      expect(offlineMessages).toHaveLength(1)
    })

    it('recovers from crash: reuses messageIds if batch pending', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      // Pre-seed: simulate append succeeded, review failed
      // Manually add messages to thread to simulate prior append
      const msg1Id = threadStore.append({ source: 'offline', role: 'user', text: 'recovered msg 1' }).id
      const msg2Id = threadStore.append({ source: 'offline', role: 'assistant', text: 'recovered msg 2' }).id
      const preCreatedMsgIds = [msg1Id, msg2Id]

      offlineBatchStore.create('batch-crash', { messageIds: preCreatedMsgIds })

      // Now replay with same batchId but different exchanges
      const body = JSON.stringify({
        batchId: 'batch-crash',
        exchanges: [
          { role: 'user', text: 'different msg' }
        ]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      const response = JSON.parse(res.getBody())
      expect(response.ok).toBe(true)
      expect(response.data.messageIds).toEqual(preCreatedMsgIds)

      // Verify thread still has original 2 messages, no new ones added
      const state = threadStore.getState()
      const offlineMessages = state.messages.filter(m => m.source === 'offline')
      expect(offlineMessages).toHaveLength(2)
    })

    it('returns 400 on missing batchId', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        exchanges: [{ role: 'user', text: 'test' }]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('batchId')
    })

    it('returns 400 on empty batchId', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: '',
        exchanges: [{ role: 'user', text: 'test' }]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
    })

    it('returns 400 on missing exchanges', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-no-exchanges'
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('exchanges')
    })

    it('returns 400 on empty exchanges array', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-empty-exchanges',
        exchanges: []
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
    })

    it('returns 400 on invalid exchange shape', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const body = JSON.stringify({
        batchId: 'batch-bad-shape',
        exchanges: [
          { role: 'user' }
        ]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('exchange')
    })

    it('returns 400 on invalid JSON', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/offline-batch', 'not valid json')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('Invalid JSON')
    })

    it('returns 500 on runSession failure, leaves batch pending', async () => {
      const failingRunSession = async function* () {
        throw new Error('Session failed')
      }

      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: failingRunSession
      })

      const body = JSON.stringify({
        batchId: 'batch-fail',
        exchanges: [{ role: 'user', text: 'test' }]
      })

      const req = new MockRequest('POST', '/offline-batch', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(500)

      // Batch should still be pending so retry can re-run review
      const batch = offlineBatchStore.get('batch-fail')
      expect(batch.status).toBe('pending')
    })
  })

  describe('routing', () => {
    it('returns false for non-/offline-batch routes', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('GET', '/offline-batch', null)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for POST to other paths', async () => {
      const router = createOfflineBatchApiRouter({
        threadStore,
        offlineBatchStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/different', JSON.stringify({ batchId: 'test' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
