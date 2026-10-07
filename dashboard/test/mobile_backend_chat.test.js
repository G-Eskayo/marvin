import { describe, it, expect, beforeEach } from 'vitest'
import { handleChatRequest, getCurrentSessionId, resetSessionId } from '../mobile-backend/chat.js'

class MockRequest {
  constructor(body) {
    this.method = 'POST'
    this.url = '/chat'
    this.body = body
    this.listeners = {}
    this.destroyed = false

    // Schedule events to fire after attach handlers are called
    setImmediate(() => {
      if (!this.destroyed) {
        // Emit data event with body
        if (this.body && this.listeners.data) {
          this.listeners.data.forEach((h) => h(Buffer.from(this.body)))
        }
        // Emit end event
        if (this.listeners.end) {
          this.listeners.end.forEach((h) => h())
        }
      }
    })
  }

  on(event, handler) {
    if (!this.listeners[event]) {
      this.listeners[event] = []
    }
    this.listeners[event].push(handler)
    return this
  }

  emit(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach((handler) => handler(data))
    }
  }

  destroy() {
    this.destroyed = true
  }
}

class MockResponse {
  constructor() {
    this.statusCode = null
    this.headers = {}
    this.chunks = []
    this.ended = false
  }

  writeHead(status, headers = {}) {
    this.statusCode = status
    this.headers = headers
    return this
  }

  write(chunk) {
    this.chunks.push(chunk)
  }

  end(chunk) {
    if (chunk) {
      this.chunks.push(chunk)
    }
    this.ended = true
  }

  getBody() {
    return this.chunks.join('')
  }
}

describe('chat', () => {
  beforeEach(() => {
    resetSessionId()
  })

  describe('handleChatRequest', () => {
    it('returns 400 for missing message field', async () => {
      const req = new MockRequest('{}')
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: async () => ({}) })

      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('missing or non-string message field')
    })

    it('returns 400 for empty message', async () => {
      const req = new MockRequest('{"message": ""}')
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: async () => ({}) })

      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('message cannot be empty')
    })

    it('returns 400 for whitespace-only message', async () => {
      const req = new MockRequest('{"message": "   "}')
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: async () => ({}) })

      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('message cannot be empty')
    })

    it('returns 400 for invalid JSON body', async () => {
      const req = new MockRequest('not json')
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: async () => ({}) })

      expect(res.statusCode).toBe(400)
    })

    it('streams events as NDJSON on success', async () => {
      const mockEvents = [
        { type: 'session_start', sessionId: 'sess-123' },
        { type: 'text_delta', text: 'Hello' },
        { type: 'text_delta', text: ' world' },
        { type: 'result', isError: false, resultText: 'Hello world' }
      ]

      const mockRunSession = async () => ({
        events: mockEvents,
        sessionId: 'sess-123'
      })

      const req = new MockRequest('{"message": "Hello"}')
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: mockRunSession })

      expect(res.statusCode).toBe(200)
      expect(res.headers['Content-Type']).toBe('application/x-ndjson')
      expect(res.ended).toBe(true)

      const body = res.getBody()
      const lines = body.trim().split('\n')
      expect(lines).toHaveLength(mockEvents.length)

      const firstLine = JSON.parse(lines[0])
      expect(firstLine.type).toBe('session_start')
    })

    it('updates session ID from run response', async () => {
      const mockRunSession = async () => ({
        events: [],
        sessionId: 'sess-new-456'
      })

      const req = new MockRequest('{"message": "Hello"}')
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: mockRunSession })

      expect(getCurrentSessionId()).toBe('sess-new-456')
    })

    it('reuses session ID on next request', async () => {
      const runCalls = []

      const mockRunSession = async (opts) => {
        runCalls.push(opts.sessionId)
        return {
          events: [],
          sessionId: 'sess-persistent'
        }
      }

      // First request
      let req = new MockRequest('{"message": "First"}')
      let res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: mockRunSession })
      expect(runCalls[0]).toBeNull() // No prior session

      // Second request should reuse
      req = new MockRequest('{"message": "Second"}')
      res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: mockRunSession })
      expect(runCalls[1]).toBe('sess-persistent')
    })

    it('includes error event on runner failure', async () => {
      const mockRunSession = async () => {
        throw new Error('Runner failed')
      }

      const req = new MockRequest('{"message": "Hello"}')
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: mockRunSession })

      expect(res.statusCode).toBe(200)
      const lines = res.getBody().trim().split('\n')
      const lastLine = JSON.parse(lines[lines.length - 1])
      expect(lastLine.type).toBe('error')
      expect(lastLine.message).toBe('Runner failed')
    })

    it('returns 404 for wrong method', async () => {
      const req = new MockRequest('{}')
      req.method = 'GET'
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: async () => ({}) })

      expect(res.statusCode).toBe(404)
    })

    it('returns 404 for wrong path', async () => {
      const req = new MockRequest('{}')
      req.url = '/other'
      const res = new MockResponse()

      await handleChatRequest(req, res, { runSessionFn: async () => ({}) })

      expect(res.statusCode).toBe(404)
    })
  })
})
