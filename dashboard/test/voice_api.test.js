import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createVoiceApiRouter } from '../mobile-backend/voice_api.js'

describe('voice_api', () => {
  let router
  let mockThreadStore
  let mockRunSession
  let mockCallFastBrain
  let mockChooseBrain
  let mockLogStage

  beforeEach(() => {
    mockThreadStore = {
      findByClientId: vi.fn().mockReturnValue(null),
      append: vi.fn((msg) => ({ id: 'msg-' + Date.now(), ...msg })),
      currentSession: vi.fn().mockReturnValue('sess-123'),
      setCurrentSession: vi.fn(),
      backfillSession: vi.fn()
    }

    // Create an async generator function
    async function* sessionGenerator() {
      yield { type: 'text', text: 'Test ' }
      yield { type: 'text', text: 'response' }
      yield { type: 'result', text: 'Test response', sessionId: 'sess-123' }
    }

    mockRunSession = vi.fn(sessionGenerator)

    mockCallFastBrain = vi.fn().mockResolvedValue('Fast brain response')

    mockChooseBrain = vi.fn().mockResolvedValue({
      type: 'deep',
      name: 'Deep Brain'
    })

    mockLogStage = vi.fn().mockResolvedValue(undefined)

    router = createVoiceApiRouter({
      threadStore: mockThreadStore,
      runSession: mockRunSession,
      callFastBrain: mockCallFastBrain,
      chooseBrain: mockChooseBrain,
      logStage: mockLogStage,
      permissionHookPath: '/tmp/hook.js'
    })
  })

  it('rejects requests without POST method', async () => {
    const req = { method: 'GET', url: '/voice', headers: { host: 'localhost' } }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      end: vi.fn()
    }

    const handled = await router(req, res)
    expect(handled).toBe(false)
  })

  it('rejects requests to non-/voice paths', async () => {
    const req = { method: 'POST', url: '/chat', headers: { host: 'localhost' } }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      end: vi.fn()
    }

    const handled = await router(req, res)
    expect(handled).toBe(false)
  })

  it('rejects empty text', async () => {
    const body = JSON.stringify({ text: '', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      end: vi.fn()
    }

    await router(req, res)
    expect(res.writeHead).toHaveBeenCalledWith(expect.any(Number), expect.any(Object))
    const callArg = res.writeHead.mock.calls[0][0]
    expect([400, 422]).toContain(callArg)
  })

  it('rejects invalid device enum', async () => {
    const body = JSON.stringify({ text: 'Hello', device: 'invalid' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      end: vi.fn()
    }

    await router(req, res)
    expect(res.writeHead).toHaveBeenCalledWith(expect.any(Number), expect.any(Object))
    const callArg = res.writeHead.mock.calls[0][0]
    expect([400, 422]).toContain(callArg)
  })

  it('accepts valid device enums case-insensitively', async () => {
    const devices = ['HomePod', 'MAC', 'iPhONE', 'watch']

    for (const device of devices) {
      mockThreadStore.findByClientId.mockReturnValue(null)
      mockThreadStore.append.mockReturnValue({ id: 'msg-' + Date.now() })

      const body = JSON.stringify({ text: 'Hello', device })
      const req = {
        method: 'POST',
        url: '/voice',
        headers: { host: 'localhost' },
        [Symbol.asyncIterator]: async function* () {
          yield body
        }
      }
      const res = {
        writeHead: vi.fn().mockReturnThis(),
        write: vi.fn(),
        end: vi.fn()
      }

      await router(req, res)
      // Should succeed (200 status) not return a 4xx error
      const statusCode = res.writeHead.mock.calls[0]?.[0]
      expect(statusCode).toBe(200)
      expect(mockChooseBrain).toHaveBeenCalled()
    }
  })

  it('logs received, routed, and token stages', async () => {
    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    expect(mockLogStage).toHaveBeenCalledWith(
      expect.any(String),
      'received',
      expect.any(Number),
      expect.any(Object)
    )

    expect(mockLogStage).toHaveBeenCalledWith(
      expect.any(String),
      'routed',
      expect.any(Number),
      expect.any(Object)
    )
  })

  it('deduplicates by clientId', async () => {
    mockThreadStore.findByClientId.mockReturnValue({ id: 'existing-msg' })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone', clientId: 'dup-123' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      end: vi.fn()
    }

    await router(req, res)

    // Should not call runSession or callFastBrain when deduped
    expect(mockRunSession).not.toHaveBeenCalled()
    expect(mockCallFastBrain).not.toHaveBeenCalled()
  })

  it('calls chooseBrain to select brain type', async () => {
    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    expect(mockChooseBrain).toHaveBeenCalledWith('Hello', expect.any(Object))
  })

  it('uses deep brain path when chosen', async () => {
    mockChooseBrain.mockResolvedValue({ type: 'deep', name: 'Deep Brain' })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    expect(mockRunSession).toHaveBeenCalled()
    expect(mockCallFastBrain).not.toHaveBeenCalled()
  })

  it('uses fast brain path when chosen', async () => {
    mockChooseBrain.mockResolvedValue({ type: 'fast', name: 'Fast Brain' })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    expect(mockCallFastBrain).toHaveBeenCalled()
    expect(mockRunSession).not.toHaveBeenCalled()
  })

  it('appends user and assistant messages to thread store', async () => {
    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    const appendCalls = mockThreadStore.append.mock.calls
    expect(appendCalls.length).toBeGreaterThanOrEqual(2)

    // Check that user message was appended
    const userMessage = appendCalls.find(call => call[0].role === 'user')
    expect(userMessage).toBeDefined()
    expect(userMessage[0]).toEqual(
      expect.objectContaining({
        source: 'voice',
        role: 'user',
        text: 'Hello'
      })
    )

    // Check that assistant message was appended with source: 'voice'
    const assistantMessage = appendCalls.find(call => call[0].role === 'assistant')
    expect(assistantMessage).toBeDefined()
    expect(assistantMessage[0]).toEqual(
      expect.objectContaining({
        source: 'voice',
        role: 'assistant'
      })
    )
    // Assistant text should not be empty
    expect(assistantMessage[0].text).toBeTruthy()
  })

  it('preserves word boundaries across streaming deltas', async () => {
    // Test that "Test " + "response" doesn't become "Testresponse"
    async function* delimitedSessionGenerator() {
      yield { type: 'text', text: 'Test ' }
      yield { type: 'text', text: 'response.' }
      yield { type: 'result', sessionId: 'sess-123' }
    }

    mockRunSession = vi.fn(delimitedSessionGenerator)

    router = createVoiceApiRouter({
      threadStore: mockThreadStore,
      runSession: mockRunSession,
      callFastBrain: mockCallFastBrain,
      chooseBrain: mockChooseBrain,
      logStage: mockLogStage,
      permissionHookPath: '/tmp/hook.js'
    })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    // Get the assistant message
    const appendCalls = mockThreadStore.append.mock.calls
    const assistantCall = appendCalls.find(call => call[0].role === 'assistant')
    const assistantText = assistantCall[0].text

    // The text should contain "Test response" with proper spacing
    expect(assistantText).toMatch(/Test\s+response/)
    expect(assistantText).not.toContain('Testresponse')
  })

  it('handles non-streaming fast brain with populated assistant message', async () => {
    mockChooseBrain.mockResolvedValue({ type: 'fast', name: 'Fast Brain' })
    // Simulates the real fast_brain behavior: when stream=false, it returns the text directly
    // and does NOT call onChunk (onChunk is only called when stream=true)
    mockCallFastBrain.mockImplementation(async ({ text, stream, onChunk }) => {
      if (stream && onChunk) {
        // Streaming mode: call onChunk
        onChunk('Fast brain response.')
      } else {
        // Non-streaming mode: return the text as a string, don't call onChunk
        return 'Fast brain response.'
      }
    })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone', stream: false })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    const appendCalls = mockThreadStore.append.mock.calls
    const assistantMessage = appendCalls.find(call => call[0].role === 'assistant')

    // In non-streaming mode, onChunk should still be called with the response
    expect(assistantMessage[0].text).toBeTruthy()
    expect(assistantMessage[0].text).toContain('Fast brain response')
  })

  it('emits fallback on deep brain error event', async () => {
    async function* errorSessionGenerator() {
      yield { type: 'error', message: 'Service error' }
    }

    mockRunSession = vi.fn(errorSessionGenerator)

    router = createVoiceApiRouter({
      threadStore: mockThreadStore,
      runSession: mockRunSession,
      callFastBrain: mockCallFastBrain,
      chooseBrain: mockChooseBrain,
      logStage: mockLogStage,
      permissionHookPath: '/tmp/hook.js'
    })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    // Should emit error and fallback sentence
    const writes = res.write.mock.calls.map(call => JSON.parse(call[0]))
    const errorEvent = writes.find(w => w.type === 'error')
    const fallbackEvent = writes.find(w => w.type === 'sentence' && w.text?.includes('error'))

    expect(errorEvent).toBeDefined()
    expect(fallbackEvent).toBeDefined()
  })

  it('appends assistant message to store even on error', async () => {
    async function* errorSessionGenerator() {
      yield { type: 'error', message: 'Service error' }
    }

    mockRunSession = vi.fn(errorSessionGenerator)

    router = createVoiceApiRouter({
      threadStore: mockThreadStore,
      runSession: mockRunSession,
      callFastBrain: mockCallFastBrain,
      chooseBrain: mockChooseBrain,
      logStage: mockLogStage,
      permissionHookPath: '/tmp/hook.js'
    })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    const appendCalls = mockThreadStore.append.mock.calls
    const assistantMessage = appendCalls.find(call => call[0].role === 'assistant')

    // Should append assistant message with fallback text
    expect(assistantMessage).toBeDefined()
    expect(assistantMessage[0].text).toContain('error')
  })

  it('sends fallback to client when deep session has no sessionId', async () => {
    // Simulate a session that produces text but never yields a result with sessionId
    async function* noSessionIdGenerator() {
      yield { type: 'text', text: 'Some response. ' }
      yield { type: 'result' } // No sessionId field
    }

    mockRunSession = vi.fn(noSessionIdGenerator)

    router = createVoiceApiRouter({
      threadStore: mockThreadStore,
      runSession: mockRunSession,
      callFastBrain: mockCallFastBrain,
      chooseBrain: mockChooseBrain,
      logStage: mockLogStage,
      permissionHookPath: '/tmp/hook.js'
    })

    const body = JSON.stringify({ text: 'Hello', device: 'iphone' })
    const req = {
      method: 'POST',
      url: '/voice',
      headers: { host: 'localhost' },
      [Symbol.asyncIterator]: async function* () {
        yield body
      }
    }
    const res = {
      writeHead: vi.fn().mockReturnThis(),
      write: vi.fn(),
      end: vi.fn()
    }

    await router(req, res)

    // Check that fallback was written to response
    const writes = res.write.mock.calls.map(call => {
      try {
        return JSON.parse(call[0])
      } catch {
        return null
      }
    }).filter(Boolean)

    const fallbackEvent = writes.find(w => w.type === 'error' && w.fallback)
    expect(fallbackEvent).toBeDefined()
    expect(fallbackEvent.fallback).toContain('temporarily unavailable')

    // Check that fallback was also appended to store
    const appendCalls = mockThreadStore.append.mock.calls
    const assistantMessage = appendCalls.find(call => call[0].role === 'assistant')
    expect(assistantMessage).toBeDefined()
    expect(assistantMessage[0].text).toContain('temporarily unavailable')
  })
})
