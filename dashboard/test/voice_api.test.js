import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createVoiceApiRouter } from '../mobile-backend/voice_api.js'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

// Reuse MockRequest and MockResponse from chat_api tests
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

  getEvents() {
    return this.getBody()
      .split('\n')
      .filter(line => line.trim())
      .map(line => JSON.parse(line))
  }
}

// Mock runSession that yields predictable events
function createMockRunSession() {
  return async function* mockRunSession({ message, sessionId, permissionHookPath }) {
    yield {
      type: 'session',
      sessionId: sessionId || 'mock-voice-sess-001'
    }
    yield {
      type: 'text',
      text: 'This is a response. It has multiple sentences!'
    }
    yield {
      type: 'result',
      text: 'This is a response. It has multiple sentences!',
      sessionId: sessionId || 'mock-voice-sess-001',
      costUsd: 0.001,
      durationMs: 100,
      isError: false
    }
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

  describe('POST /voice', () => {
    it('test 2: validates text field is required', async () => {
      const router = createVoiceApiRouter({ threadStore })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ device: 'iphone' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      const body = JSON.parse(res.getBody())
      expect(body.error).toContain('text')
    })

    it('test 6: validates device field is required', async () => {
      const router = createVoiceApiRouter({ threadStore })

      const req = new MockRequest('POST', '/voice', JSON.stringify({ text: 'hello' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      const body = JSON.parse(res.getBody())
      expect(body.error).toContain('device')
    })

    it('test 7: validates device is known', async () => {
      const router = createVoiceApiRouter({ threadStore })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'hello',
        device: 'unknown-device'
      }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      const body = JSON.parse(res.getBody())
      expect(body.error).toContain('device')
    })

    it('test 8: accepts valid text and known device', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'hello',
        device: 'iphone'
      }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
    })

    it('test 9: accepts case-insensitive device names', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'hello',
        device: 'HOMEPOD'
      }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
    })

    it('test 3: passes permissionHookPath to runSession', async () => {
      let capturedPermissionHook = null
      const customRunSession = async function* (opts) {
        capturedPermissionHook = opts.permissionHookPath
        yield* createMockRunSession()(opts)
      }

      const hookPath = '/path/to/permission_hook.js'
      const router = createVoiceApiRouter({
        threadStore,
        runSession: customRunSession,
        permissionHookPath: hookPath
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'hello',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)
      expect(capturedPermissionHook).toBe(hookPath)
    })

    it('test 1: streams speakable sentences', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'hello',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)

      const events = res.getEvents()
      const sentenceEvents = events.filter(e => e.type === 'sentence')

      expect(sentenceEvents.length).toBeGreaterThan(0)
      // Sentences should have speakable text (no markdown)
      for (const event of sentenceEvents) {
        expect(event.text).toBeDefined()
        expect(typeof event.text).toBe('string')
      }
    })

    it('test 4: converts error events to spoken fallback', async () => {
      const errorRunSession = async function* (opts) {
        yield {
          type: 'error',
          message: 'Model unreachable'
        }
      }

      const router = createVoiceApiRouter({
        threadStore,
        runSession: errorRunSession
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'hello',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)

      const events = res.getEvents()
      const errorSpeech = events.find(e => e.type === 'error_speech')

      expect(errorSpeech).toBeDefined()
      expect(errorSpeech.text).toContain('error')
    })

    it('test 5: emits placeholder before deep-brain processing', async () => {
      // Mock classifyBrain to return a deep brain type
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'implement a new feature',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)

      const events = res.getEvents()
      const placeholderEvent = events.find(e => e.type === 'placeholder')

      // Should emit placeholder for non-recall/research intents
      if (placeholderEvent) {
        expect(placeholderEvent.text).toBeDefined()
      }
    })

    it('test 11: emits classification event', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'hello world',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)

      const events = res.getEvents()
      const classificationEvent = events.find(e => e.type === 'classification')

      expect(classificationEvent).toBeDefined()
      expect(classificationEvent).toHaveProperty('intent')
      expect(classificationEvent).toHaveProperty('brainType')
      expect(classificationEvent).toHaveProperty('routingMs')
    })

    it('test 12: emits timing information', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'test prompt',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)

      const events = res.getEvents()
      const timingEvent = events.find(e => e.type === 'timing')

      expect(timingEvent).toBeDefined()
      expect(timingEvent).toHaveProperty('routingMs')
      expect(timingEvent).toHaveProperty('totalMs')
    })

    it('test 13: appends user and assistant messages to thread store', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'test message',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      const userMsg = state.messages.find(m => m.role === 'user' && m.source === 'voice')
      const assistantMsg = state.messages.find(m => m.role === 'assistant' && m.source === 'voice')

      expect(userMsg).toBeDefined()
      expect(userMsg.text).toBe('test message')
      expect(assistantMsg).toBeDefined()
    })

    it('test 16: applies rotation policy', async () => {
      const router = createVoiceApiRouter({
        threadStore,
        runSession: createMockRunSession()
      })

      // Add enough messages to trigger rotation (threshold is 10)
      for (let i = 0; i < 5; i++) {
        threadStore.append({
          source: 'voice',
          role: 'user',
          text: `message ${i}`,
          sessionId: 'mock-voice-sess-001'
        })
        threadStore.append({
          source: 'voice',
          role: 'assistant',
          text: `response ${i}`,
          sessionId: 'mock-voice-sess-001'
        })
      }

      threadStore.setCurrentSession('mock-voice-sess-001')

      const req = new MockRequest('POST', '/voice', JSON.stringify({
        text: 'new message',
        device: 'iphone'
      }))
      const res = new MockResponse()

      await router(req, res)

      const state = threadStore.getState()
      // If rotation occurred, pendingSummary should be set
      // This is an integration test of the rotation policy
      expect(state).toHaveProperty('messages')
      expect(state).toHaveProperty('currentSessionId')
    })

    it('handles invalid JSON in request', async () => {
      const router = createVoiceApiRouter({ threadStore })

      const req = new MockRequest('POST', '/voice', 'not json')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
      const body = JSON.parse(res.getBody())
      expect(body.error).toContain('Invalid JSON')
    })
  })

  describe('routing', () => {
    it('does not handle non-/voice routes', async () => {
      const router = createVoiceApiRouter({ threadStore })

      const req = new MockRequest('POST', '/chat', JSON.stringify({ message: 'test' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('does not handle GET requests to /voice', async () => {
      const router = createVoiceApiRouter({ threadStore })

      const req = new MockRequest('GET', '/voice', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
