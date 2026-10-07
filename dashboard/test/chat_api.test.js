import { describe, it, expect } from 'vitest'
import { createChatApiRouter } from '../mobile-backend/chat_api.js'

// Create a mock request object with method, url, headers, and optional body data
class MockRequest {
  constructor(method, url, body) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost' }
    this.body = body
    this._index = 0
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

describe('chat_api', () => {
  describe('POST /chat', () => {
    it('returns 400 when message is missing', async () => {
      const router = createChatApiRouter()
      const req = new MockRequest('POST', '/chat', JSON.stringify({ sessionId: 'test' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('invalid message')
    })

    it('returns 400 when body is invalid JSON', async () => {
      const router = createChatApiRouter()
      const req = new MockRequest('POST', '/chat', 'not json')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('Invalid JSON')
    })

    it('streams events as NDJSON', async () => {
      let capturedMessage = null
      let capturedSessionId = null

      const mockRunSession = async function* ({ message, sessionId }) {
        capturedMessage = message
        capturedSessionId = sessionId
        yield { type: 'session', sessionId: 'new-session-001' }
        yield { type: 'text', text: 'Hello from test' }
        yield { type: 'result', text: 'Final result', sessionId: 'new-session-001', costUsd: 0.001, durationMs: 200, isError: false }
      }

      const router = createChatApiRouter({ runSession: mockRunSession })
      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'test message' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      expect(res.headers['Content-Type']).toBe('application/x-ndjson')
      expect(capturedMessage).toBe('test message')

      const body = res.getBody()
      const lines = body.trim().split('\n')
      expect(lines).toHaveLength(3)
      expect(JSON.parse(lines[0])).toEqual({ type: 'session', sessionId: 'new-session-001' })
      expect(JSON.parse(lines[1])).toEqual({ type: 'text', text: 'Hello from test' })
      expect(JSON.parse(lines[2]).type).toBe('result')
    })

    it('passes sessionId to runSession when provided', async () => {
      let capturedSessionId = null

      const mockRunSession = async function* ({ message, sessionId }) {
        capturedSessionId = sessionId
        yield { type: 'result', text: 'OK', sessionId: 'same-session', costUsd: 0, durationMs: 100, isError: false }
      }

      const router = createChatApiRouter({ runSession: mockRunSession })
      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'resume test', sessionId: 'same-session' }))
      const res = new MockResponse()

      await router(req, res)
      expect(capturedSessionId).toBe('same-session')
    })

    it('surfaces runSession errors in the event stream', async () => {
      const mockRunSession = async function* () {
        yield { type: 'text', text: 'Start' }
        throw new Error('Test error occurred')
      }

      const router = createChatApiRouter({ runSession: mockRunSession })
      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'error test' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)

      const body = res.getBody()
      const lines = body.trim().split('\n')
      expect(lines.length).toBeGreaterThanOrEqual(2)
      expect(JSON.parse(lines[lines.length - 1]).type).toBe('error')
      expect(JSON.parse(lines[lines.length - 1]).message).toContain('Test error occurred')
    })
  })

  describe('routing', () => {
    it('returns false for non-/chat routes', async () => {
      const router = createChatApiRouter()
      const req = new MockRequest('GET', '/other', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for POST requests to other paths', async () => {
      const router = createChatApiRouter()
      const req = new MockRequest('POST', '/different', JSON.stringify({ message: 'test' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
