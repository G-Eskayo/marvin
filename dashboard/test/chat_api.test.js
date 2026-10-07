import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createChatApiRouter } from '../mobile-backend/chat_api.js'
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
      text: `Echo: ${message}`
    }
    yield {
      type: 'result',
      text: `Echo: ${message}`,
      sessionId: sessionId || 'mock-sess-001',
      costUsd: 0.001,
      durationMs: 100,
      isError: false
    }
  }
}

describe('chat_api', () => {
  let tempDir, threadStore

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), 'chat-api-test-'))
    threadStore = createThreadStore({ path: path.join(tempDir, 'thread.json') })
  })

  afterEach(async () => {
    await rm(tempDir, { recursive: true, force: true })
  })

  describe('POST /chat', () => {
    it('accepts message body without clientSessionId', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'hello' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
    })

    it('appends user message to thread store', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'test message' }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      expect(state.messages.length).toBeGreaterThanOrEqual(1)
      const userMsg = state.messages.find(m => m.role === 'user')
      expect(userMsg).toMatchObject({
        role: 'user',
        text: 'test message',
        source: 'chat'
      })
    })

    it('appends assistant message to thread store', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'test' }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const assistantMsg = state.messages.find(m => m.role === 'assistant')
      expect(assistantMsg).toBeDefined()
      expect(assistantMsg.text).toContain('Echo: test')
    })

    it('backfills user message sessionId from result event', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'test' }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const userMsg = state.messages.find(m => m.role === 'user')
      const assistantMsg = state.messages.find(m => m.role === 'assistant')

      expect(userMsg.sessionId).toBe('mock-sess-001')
      expect(assistantMsg.sessionId).toBe('mock-sess-001')
    })

    it('sets current session from result event', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'test' }))
      const res = new MockResponse()

      await router(req, res)

      expect(threadStore.currentSession()).toBe('mock-sess-001')
    })

    it('resumes with currentSessionId if one exists', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      threadStore.setCurrentSession('existing-sess-123')

      let capturedSessionId = null
      const customMockRunSession = async function* (opts) {
        capturedSessionId = opts.sessionId
        yield* createMockRunSession()({ ...opts, sessionId: opts.sessionId })
      }

      const router2 = createChatApiRouter({
        threadStore,
        runSession: customMockRunSession
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'continue' }))
      const res = new MockResponse()

      await router2(req, res)

      expect(capturedSessionId).toBe('existing-sess-123')
    })

    it('prepends pending summary to message text sent to runSession', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      threadStore.rotate({
        summary: 'Previously discussed: cats are cute',
        fromSessionId: 'old-sess'
      })

      let capturedMessage = null
      const customMockRunSession = async function* (opts) {
        capturedMessage = opts.message
        yield* createMockRunSession()(opts)
      }

      const router2 = createChatApiRouter({
        threadStore,
        runSession: customMockRunSession
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'what was that about' }))
      const res = new MockResponse()

      await router2(req, res)

      expect(capturedMessage).toContain('Previously discussed: cats are cute')
      expect(capturedMessage).toContain('what was that about')
    })

    it('consumes pending summary after exchange', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      threadStore.rotate({
        summary: 'temp summary',
        fromSessionId: 'old-sess'
      })

      const router2 = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'test' }))
      const res = new MockResponse()

      await router2(req, res)

      expect(threadStore.getState().pendingSummary).toBeNull()
    })

    it('returns ndjson stream with events', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'hello' }))
      const res = new MockResponse()

      await router(req, res)

      const body = res.getBody()
      const lines = body.trim().split('\n').filter(l => l.length > 0)
      expect(lines.length).toBeGreaterThan(0)

      for (const line of lines) {
        const parsed = JSON.parse(line)
        expect(parsed).toHaveProperty('type')
      }
    })

    it('rejects missing message field', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', JSON.stringify({}))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('Missing or invalid message field')
    })

    it('rejects invalid JSON body', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/chat', 'not valid json')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('Invalid JSON')
    })
  })

  describe('GET /thread', () => {
    it('returns paged thread messages', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      threadStore.append({ source: 'chat', role: 'user', text: 'msg1', sessionId: 'sess-1' })
      threadStore.append({ source: 'chat', role: 'user', text: 'msg2', sessionId: 'sess-1' })

      const req = new MockRequest('GET', '/thread?limit=10', null)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)

      const response = JSON.parse(res.getBody())
      expect(response.ok).toBe(true)
      expect(response.data).toHaveLength(2)
      expect(response.data[0].text).toBe('msg2') // newest first
      expect(response.data[1].text).toBe('msg1')
    })

    it('respects limit query parameter', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      for (let i = 0; i < 5; i++) {
        threadStore.append({ source: 'chat', role: 'user', text: `msg${i}`, sessionId: 'sess-1' })
      }

      const req = new MockRequest('GET', '/thread?limit=2', null)
      const res = new MockResponse()

      await router(req, res)
      const response = JSON.parse(res.getBody())
      expect(response.data).toHaveLength(2)
    })

    it('handles before cursor for pagination', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const ids = []
      for (let i = 0; i < 5; i++) {
        threadStore.append({ source: 'chat', role: 'user', text: `msg${i}`, sessionId: 'sess-1' })
        ids.push(threadStore.getState().messages[i].id)
      }

      const beforeId = ids[ids.length - 3] // msg2
      const req = new MockRequest('GET', `/thread?limit=10&before=${beforeId}`, null)
      const res = new MockResponse()

      await router(req, res)
      const response = JSON.parse(res.getBody())
      expect(response.ok).toBe(true)
      expect(response.data.length).toBeGreaterThan(0)
    })
  })

  describe('routing', () => {
    it('returns false for non-/chat and non-/thread routes', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('GET', '/unknown', null)
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for POST requests to other paths', async () => {
      const router = createChatApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/different', JSON.stringify({ message: 'test' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
