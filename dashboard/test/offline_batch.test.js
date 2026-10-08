import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { processOfflineBatch } from '../mobile-backend/offline_batch.js'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

// Mock runSession generator
function createMockRunSession() {
  return async function* mockRunSession({ message }) {
    yield {
      type: 'session',
      sessionId: 'mock-offline-sess'
    }
    yield {
      type: 'text',
      text: 'Memory review processed'
    }
    yield {
      type: 'result',
      text: 'Memory review processed',
      sessionId: 'mock-offline-sess',
      costUsd: 0.001,
      durationMs: 100,
      isError: false
    }
  }
}

describe('offline_batch', () => {
  let tempDir, threadStore

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), 'offline-batch-test-'))
    threadStore = createThreadStore({ path: path.join(tempDir, 'thread.json') })
  })

  afterEach(async () => {
    await rm(tempDir, { recursive: true, force: true })
  })

  describe('processOfflineBatch', () => {
    it('appends new exchanges with offline source', async () => {
      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'offline-1',
            role: 'user',
            text: 'first offline message'
          }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const state = threadStore.getState()
      expect(state.messages).toHaveLength(1)
      expect(state.messages[0]).toMatchObject({
        source: 'offline',
        role: 'user',
        text: 'first offline message',
        clientId: 'offline-1'
      })
      expect(result.appended).toBe(1)
      expect(result.skipped).toBe(0)
    })

    it('deduplicates exchanges by clientId', async () => {
      threadStore.append({
        source: 'offline',
        role: 'user',
        text: 'first offline message',
        clientId: 'offline-1'
      })

      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'offline-1',
            role: 'user',
            text: 'first offline message'
          }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const state = threadStore.getState()
      expect(state.messages).toHaveLength(1)
      expect(result.appended).toBe(0)
      expect(result.skipped).toBe(1)
      expect(result.reviewed).toBe(false)
    })

    it('handles mixed new and duplicate exchanges', async () => {
      threadStore.append({
        source: 'offline',
        role: 'user',
        text: 'existing message',
        clientId: 'offline-existing'
      })

      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'offline-existing',
            role: 'user',
            text: 'existing message'
          },
          {
            clientId: 'offline-new',
            role: 'user',
            text: 'new message'
          }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const state = threadStore.getState()
      expect(state.messages).toHaveLength(2)
      expect(result.appended).toBe(1)
      expect(result.skipped).toBe(1)
      expect(result.reviewed).toBe(true)
    })

    it('skips review if all exchanges are duplicates', async () => {
      threadStore.append({
        source: 'offline',
        role: 'user',
        text: 'existing',
        clientId: 'dup-1'
      })

      let reviewSessionCalled = false
      const mockRunSessionFn = async function* () {
        reviewSessionCalled = true
        yield {
          type: 'result',
          sessionId: 'review-sess'
        }
      }

      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'dup-1',
            role: 'user',
            text: 'existing'
          }
        ],
        threadStore,
        runSessionFn: mockRunSessionFn
      })

      expect(result.appended).toBe(0)
      expect(result.reviewed).toBe(false)
      expect(reviewSessionCalled).toBe(false)
    })

    it('backfills sessionId from review session', async () => {
      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'offline-2',
            role: 'user',
            text: 'message to review'
          }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const state = threadStore.getState()
      expect(state.messages[0].sessionId).toBe('mock-offline-sess')
      expect(result.sessionId).toBe('mock-offline-sess')
    })

    it('handles review session error without losing messages', async () => {
      const failingMockRunSession = async function* () {
        yield {
          type: 'error',
          message: 'Session failed'
        }
      }

      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'offline-err',
            role: 'user',
            text: 'message before error'
          }
        ],
        threadStore,
        runSessionFn: failingMockRunSession
      })

      const state = threadStore.getState()
      expect(state.messages).toHaveLength(1)
      expect(state.messages[0].text).toBe('message before error')
      expect(result.appended).toBe(1)
      expect(result.error).toBeDefined()
    })

    it('preserves original timestamp from exchange if provided', async () => {
      const customTs = 1234567890
      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'offline-ts',
            role: 'user',
            text: 'timestamped message',
            ts: customTs
          }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const state = threadStore.getState()
      expect(state.messages[0].ts).toBe(customTs)
    })

    it('generates ts if not provided', async () => {
      const beforeTime = Date.now()
      const result = await processOfflineBatch({
        exchanges: [
          {
            clientId: 'offline-no-ts',
            role: 'user',
            text: 'auto-timestamped'
          }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      const afterTime = Date.now()
      const state = threadStore.getState()
      expect(state.messages[0].ts).toBeGreaterThanOrEqual(beforeTime)
      expect(state.messages[0].ts).toBeLessThanOrEqual(afterTime)
    })

    it('includes appended count in result', async () => {
      const result = await processOfflineBatch({
        exchanges: [
          { clientId: 'msg-1', role: 'user', text: 'msg1' },
          { clientId: 'msg-2', role: 'user', text: 'msg2' },
          { clientId: 'msg-3', role: 'user', text: 'msg3' }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      expect(result.appended).toBe(3)
      expect(result.skipped).toBe(0)
    })

    it('returns ok: true on successful batch', async () => {
      const result = await processOfflineBatch({
        exchanges: [
          { clientId: 'ok-test', role: 'user', text: 'test' }
        ],
        threadStore,
        runSessionFn: createMockRunSession()
      })

      expect(result.ok).toBe(true)
    })
  })
})
