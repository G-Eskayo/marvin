import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createVoiceApiRouter } from '../mobile-backend/voice_api.js'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

// Mock request/response helpers
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

// Mock route classifier
function createMockRouteClassifier() {
  return async function mockRouteClassify(text) {
    // Simulate routing: research intents go to fast, others to deep
    return text.toLowerCase().includes('research') ? 'research' : 'architecture'
  }
}

// Mock brains
function createMockFastBrain() {
  return async function* mockFastBrain({ message }) {
    yield { type: 'text', text: 'Quick response: ' }
    yield { type: 'text', text: message }
  }
}

function createMockDeepBrain() {
  return async function* mockDeepBrain({ message, sessionId }) {
    yield {
      type: 'session',
      sessionId: sessionId || 'mock-sess-001'
    }
    yield { type: 'text', text: 'Deep thought: ' }
    yield { type: 'text', text: message }
    yield {
      type: 'result',
      text: `Deep thought: ${message}`,
      sessionId: sessionId || 'mock-sess-001',
      costUsd: 0.002,
      durationMs: 200,
      isError: false
    }
  }
}

function createMockCannedResponse() {
  return async function* mockCannedResponse() {
    yield { type: 'text', text: 'I encountered an error, but I still have a response for you.' }
  }
}

describe('voice_api', () => {
  let tempDir, threadStore

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), 'voice-api-test-'))
    threadStore = createThreadStore({ path: path.join(tempDir, 'thread.json') })
  })

  afterEach(async () => {
    await rm(tempDir, { recursive: true, force: true })
  })

  describe('POST /voice input validation', () => {
    it('rejects missing text field', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
    })

    it('rejects non-string text field', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 123 }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
    })

    // Defect 7: Test `from` field validation (unknown device rejected)
    it('rejects missing or invalid from field', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'unknown-device', text: 'hello' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('unknown device')
    })

    // Defect 7: Test text length cap enforcement
    it('rejects text exceeding maximum length', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      const longText = 'a'.repeat(5000)
      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: longText }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      expect(res.getBody()).toContain('exceeds maximum length')
    })

    it('accepts valid text and from fields', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'hello' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
    })
  })

  describe('POST /voice routing and brain selection', () => {
    it('routes to fast brain for research intents', async () => {
      let usedFastBrain = false
      let usedDeepBrain = false

      const mockFastBrain = async function* () {
        usedFastBrain = true
        yield { type: 'text', text: 'fast response' }
      }

      const mockDeepBrain = async function* () {
        usedDeepBrain = true
        yield { type: 'text', text: 'deep response' }
      }

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: mockFastBrain,
        deepBrain: mockDeepBrain,
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'research this topic' }))
      const res = new MockResponse()

      await router(req, res)

      expect(usedFastBrain).toBe(true)
      expect(usedDeepBrain).toBe(false)
    })

    it('routes to deep brain for architecture intents', async () => {
      let usedFastBrain = false
      let usedDeepBrain = false

      const mockFastBrain = async function* () {
        usedFastBrain = true
        yield { type: 'text', text: 'fast response' }
      }

      const mockDeepBrain = async function* () {
        usedDeepBrain = true
        yield {
          type: 'session',
          sessionId: 'sess-001'
        }
        yield { type: 'text', text: 'deep response' }
        yield {
          type: 'result',
          text: 'deep response',
          sessionId: 'sess-001',
          costUsd: 0.002,
          durationMs: 200,
          isError: false
        }
      }

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: mockFastBrain,
        deepBrain: mockDeepBrain,
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'how should we design this' }))
      const res = new MockResponse()

      await router(req, res)

      expect(usedFastBrain).toBe(false)
      expect(usedDeepBrain).toBe(true)
    })
  })

  describe('POST /voice thread store appending', () => {
    it('appends user message with source: voice', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'test voice input' }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const userMsg = state.messages.find(m => m.role === 'user')
      expect(userMsg).toBeDefined()
      expect(userMsg.text).toBe('test voice input')
      expect(userMsg.source).toBe('voice')
    })

    it('appends assistant message with source: voice', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'hello' }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const assistantMsg = state.messages.find(m => m.role === 'assistant')
      expect(assistantMsg).toBeDefined()
      expect(assistantMsg.source).toBe('voice')
    })
  })

  describe('POST /voice fallback behavior', () => {
    it('falls back to canned response when deep brain fails', async () => {
      const mockDeepBrainFails = async function* () {
        throw new Error('Brain failure')
      }

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: mockDeepBrainFails,
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'how should we design this' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)

      const state = threadStore.getState()
      const assistantMsg = state.messages.find(m => m.role === 'assistant')
      expect(assistantMsg).toBeDefined()
    })
  })

  describe('POST /voice speakable text processing', () => {
    // Defect 2: Test that streamed text events are cleaned before sending to client
    it('applies toSpeakable to streamed text events sent to client', async () => {
      const mockDeepBrain = async function* () {
        yield {
          type: 'session',
          sessionId: 'sess-001'
        }
        yield {
          type: 'text',
          text: 'Check out [this link](https://example.com) for **bold**'
        }
        yield {
          type: 'result',
          text: 'Check out [this link](https://example.com) for **bold**',
          sessionId: 'sess-001',
          costUsd: 0.002,
          durationMs: 200,
          isError: false
        }
      }

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: mockDeepBrain,
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'design' }))
      const res = new MockResponse()

      await router(req, res)

      // Check that streamed text events had toSpeakable applied
      const body = res.getBody()
      const lines = body.split('\n').filter(l => l.trim())
      const textEvents = lines.map(l => JSON.parse(l)).filter(e => e.type === 'text')

      // All streamed text events should have markdown/URLs stripped
      for (const event of textEvents) {
        expect(event.text).not.toContain('**')
        expect(event.text).not.toContain('https://')
      }
    })

    it('applies toSpeakable to assistant response stored in thread', async () => {
      const mockDeepBrain = async function* () {
        yield {
          type: 'session',
          sessionId: 'sess-001'
        }
        yield {
          type: 'text',
          text: 'Check out [this link](https://example.com) for more **bold** text'
        }
        yield {
          type: 'result',
          text: 'Check out [this link](https://example.com) for more **bold** text',
          sessionId: 'sess-001',
          costUsd: 0.002,
          durationMs: 200,
          isError: false
        }
      }

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: mockDeepBrain,
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'design' }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const assistantMsg = state.messages.find(m => m.role === 'assistant')
      // Markdown should be stripped, link text preserved
      expect(assistantMsg.text).toContain('this link')
      expect(assistantMsg.text).not.toContain('https://')
      expect(assistantMsg.text).not.toContain('**')
    })
  })

  describe('GET /thread pagination', () => {
    it('supports GET /thread with pagination', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: createMockDeepBrain(),
        cannedResponse: createMockCannedResponse()
      })

      // Add some messages first
      const req1 = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'hello' }))
      const res1 = new MockResponse()
      await router(req1, res1)

      const req1b = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'hello 2' }))
      const res1b = new MockResponse()
      await router(req1b, res1b)

      // Now fetch thread
      const reqThread = new MockRequest('GET', '/thread?limit=1', null)
      const resThread = new MockResponse()
      const handled = await router(reqThread, resThread)

      expect(handled).toBe(true)
      expect(resThread.statusCode).toBe(200)
      const body = JSON.parse(resThread.getBody())
      expect(body.ok).toBe(true)
      expect(body.data).toBeDefined()
    })
  })

  describe('POST /voice routing and fallback behavior', () => {
    // Defect 4: Test that routing failure falls back to deep brain, not error
    it('falls back to deep brain when route classifier fails', async () => {
      let usedDeepBrain = false
      const failingRouteClassifier = async () => {
        throw new Error('Routing service unavailable')
      }

      const mockDeepBrain = async function* () {
        usedDeepBrain = true
        yield {
          type: 'session',
          sessionId: 'sess-001'
        }
        yield { type: 'text', text: 'Fallback response from deep brain' }
        yield {
          type: 'result',
          text: 'Fallback response from deep brain',
          sessionId: 'sess-001',
          costUsd: 0.002,
          durationMs: 200,
          isError: false
        }
      }

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: failingRouteClassifier,
        fastBrain: createMockFastBrain(),
        deepBrain: mockDeepBrain,
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'test' }))
      const res = new MockResponse()

      await router(req, res)

      expect(usedDeepBrain).toBe(true)
      expect(res.statusCode).toBe(200)
      const state = threadStore.getState()
      const userMsg = state.messages.find(m => m.role === 'user')
      expect(userMsg).toBeDefined()  // User message should still be appended
    })

    // Defect 3: Test that brain error + no canned response still produces non-empty message
    it('produces non-empty assistant message even when brain fails and no canned response', async () => {
      const failingBrain = async function* () {
        throw new Error('Brain crash')
      }

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: failingBrain,
        cannedResponse: undefined  // No canned response
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'test' }))
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      const state = threadStore.getState()
      const assistantMsg = state.messages.find(m => m.role === 'assistant')
      expect(assistantMsg).toBeDefined()
      expect(assistantMsg.text).toBeTruthy()  // Should have non-empty fallback message
      expect(assistantMsg.text).toContain('error')  // Fallback should explain the error
    })

    // Defect 5: Test that permissionHookPath is passed to deepBrain
    it('passes permissionHookPath to deepBrain for permission gating', async () => {
      let passedPermissionHookPath = null
      const mockDeepBrain = async function* ({ message, sessionId, permissionHookPath }) {
        passedPermissionHookPath = permissionHookPath
        yield {
          type: 'session',
          sessionId: sessionId || 'sess-001'
        }
        yield { type: 'text', text: 'response' }
        yield {
          type: 'result',
          text: 'response',
          sessionId: sessionId || 'sess-001',
          costUsd: 0.002,
          durationMs: 200,
          isError: false
        }
      }

      const hookPath = '/path/to/permission/hook'
      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: mockDeepBrain,
        cannedResponse: createMockCannedResponse(),
        permissionHookPath: hookPath
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'test' }))
      const res = new MockResponse()

      await router(req, res)

      expect(passedPermissionHookPath).toBe(hookPath)
    })
  })

  describe('POST /voice session management', () => {
    // Defect 6: Test that voice sessions don't overwrite chat's current session
    it('appends voice turn with sessionId but does not set as current session', async () => {
      const mockDeepBrain = async function* () {
        yield {
          type: 'session',
          sessionId: 'voice-sess-001'
        }
        yield { type: 'text', text: 'voice response' }
        yield {
          type: 'result',
          text: 'voice response',
          sessionId: 'voice-sess-001',
          costUsd: 0.002,
          durationMs: 200,
          isError: false
        }
      }

      // Pre-set a chat session as current
      threadStore.setCurrentSession('chat-sess-999')

      const router = createVoiceApiRouter({
        threadStore,
        routeClassify: createMockRouteClassifier(),
        fastBrain: createMockFastBrain(),
        deepBrain: mockDeepBrain,
        cannedResponse: createMockCannedResponse()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ from: 'iphone', text: 'test' }))
      const res = new MockResponse()

      await router(req, res)

      // Current session should still be the chat session, not replaced by voice
      expect(threadStore.currentSession()).toBe('chat-sess-999')

      // But the voice turn should still be in the thread with its sessionId
      const state = threadStore.getState()
      const assistantMsg = state.messages.find(m => m.role === 'assistant')
      expect(assistantMsg.sessionId).toBe('voice-sess-001')
    })
  })
})
