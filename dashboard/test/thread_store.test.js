import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createThreadStore } from '../mobile-backend/thread_store.js'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

describe('thread_store', () => {
  let tempDir

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), 'thread-store-test-'))
  })

  afterEach(async () => {
    await rm(tempDir, { recursive: true, force: true })
  })

  describe('append', () => {
    it('appends a message with required fields', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'chat',
        role: 'user',
        text: 'hello',
        sessionId: 'sess-1'
      })

      const state = store.getState()
      expect(state.messages).toHaveLength(1)
      expect(state.messages[0]).toMatchObject({
        source: 'chat',
        role: 'user',
        text: 'hello',
        sessionId: 'sess-1'
      })
      expect(state.messages[0].id).toBeDefined()
      expect(state.messages[0].ts).toBeDefined()
    })

    it('appends a message with sessionId null initially', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'chat',
        role: 'user',
        text: 'hello'
      })

      const state = store.getState()
      expect(state.messages[0].sessionId).toBeNull()
    })

    it('appends a message with optional clientId', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'offline',
        role: 'user',
        text: 'offline message',
        clientId: 'client-123'
      })

      const state = store.getState()
      expect(state.messages[0].clientId).toBe('client-123')
    })

    it('appends a message with clientId null by default', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'chat',
        role: 'user',
        text: 'hello'
      })

      const state = store.getState()
      expect(state.messages[0].clientId).toBeNull()
    })

    it('validates source field', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      expect(() => {
        store.append({
          source: 'invalid',
          role: 'user',
          text: 'hello'
        })
      }).toThrow(/source must be one of/)
    })

    it('persists to disk synchronously', async () => {
      const filePath = path.join(tempDir, 'thread.json')
      const store1 = createThreadStore({ path: filePath })

      store1.append({
        source: 'chat',
        role: 'user',
        text: 'hello',
        sessionId: 'sess-1'
      })

      const store2 = createThreadStore({ path: filePath })
      const state2 = store2.getState()

      expect(state2.messages).toHaveLength(1)
      expect(state2.messages[0].text).toBe('hello')
    })
  })

  describe('backfillSession', () => {
    it('updates a message sessionId by message id', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'chat',
        role: 'user',
        text: 'hello'
      })

      const messageId = store.getState().messages[0].id
      store.backfillSession(messageId, 'sess-123')

      const state = store.getState()
      expect(state.messages[0].sessionId).toBe('sess-123')
    })

    it('raises error if message id not found', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      expect(() => {
        store.backfillSession('nonexistent-id', 'sess-123')
      }).toThrow(/Message not found/)
    })
  })

  describe('currentSession', () => {
    it('returns currentSessionId', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })
      store.setCurrentSession('sess-abc')

      expect(store.currentSession()).toBe('sess-abc')
    })

    it('returns null if no current session', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      expect(store.currentSession()).toBeNull()
    })
  })

  describe('setCurrentSession', () => {
    it('sets the current session', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })
      store.setCurrentSession('sess-new')

      expect(store.currentSession()).toBe('sess-new')
    })

    it('persists the change to disk', async () => {
      const filePath = path.join(tempDir, 'thread.json')
      const store1 = createThreadStore({ path: filePath })

      store1.setCurrentSession('sess-persisted')

      const store2 = createThreadStore({ path: filePath })
      expect(store2.currentSession()).toBe('sess-persisted')
    })
  })

  describe('rotate', () => {
    it('archives the current session and clears currentSessionId', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({ source: 'chat', role: 'user', text: 'msg1', sessionId: 'sess-1' })
      store.append({ source: 'chat', role: 'assistant', text: 'reply1', sessionId: 'sess-1' })
      store.setCurrentSession('sess-1')

      store.rotate({
        summary: 'discussed hello world',
        fromSessionId: 'sess-1'
      })

      const state = store.getState()
      expect(state.currentSessionId).toBeNull()
      expect(state.sessions).toHaveLength(1)
      expect(state.sessions[0]).toMatchObject({
        sessionId: 'sess-1',
        summary: 'discussed hello world'
      })
      expect(state.sessions[0].endedAt).toBeDefined()
    })

    it('sets pendingSummary', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.rotate({
        summary: 'test summary',
        fromSessionId: 'sess-1'
      })

      const state = store.getState()
      expect(state.pendingSummary).toBe('test summary')
    })

    it('persists rotation to disk', async () => {
      const filePath = path.join(tempDir, 'thread.json')
      const store1 = createThreadStore({ path: filePath })

      store1.rotate({
        summary: 'archived',
        fromSessionId: 'sess-1'
      })

      const store2 = createThreadStore({ path: filePath })
      const state2 = store2.getState()

      expect(state2.sessions).toHaveLength(1)
      expect(state2.pendingSummary).toBe('archived')
    })
  })

  describe('consumePendingSummary', () => {
    it('returns and clears the pending summary', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.rotate({
        summary: 'pending text',
        fromSessionId: 'sess-1'
      })

      const summary = store.consumePendingSummary()
      expect(summary).toBe('pending text')
      expect(store.getState().pendingSummary).toBeNull()
    })

    it('returns null if no pending summary', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      expect(store.consumePendingSummary()).toBeNull()
    })

    it('persists the cleared state to disk', async () => {
      const filePath = path.join(tempDir, 'thread.json')
      const store1 = createThreadStore({ path: filePath })

      store1.rotate({ summary: 'temp', fromSessionId: 'sess-1' })
      store1.consumePendingSummary()

      const store2 = createThreadStore({ path: filePath })
      expect(store2.getState().pendingSummary).toBeNull()
    })
  })

  describe('page', () => {
    it('returns messages in reverse chronological order (newest first)', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({ source: 'chat', role: 'user', text: 'first' })
      store.append({ source: 'chat', role: 'user', text: 'second' })
      store.append({ source: 'chat', role: 'user', text: 'third' })

      const result = store.page({ limit: 10 })
      expect(result).toHaveLength(3)
      expect(result[0].text).toBe('third')
      expect(result[1].text).toBe('second')
      expect(result[2].text).toBe('first')
    })

    it('respects limit parameter', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      for (let i = 0; i < 5; i++) {
        store.append({ source: 'chat', role: 'user', text: `msg${i}` })
      }

      const result = store.page({ limit: 2 })
      expect(result).toHaveLength(2)
      expect(result[0].text).toBe('msg4')
      expect(result[1].text).toBe('msg3')
    })

    it('paginates with before cursor', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      const ids = []
      for (let i = 0; i < 5; i++) {
        store.append({ source: 'chat', role: 'user', text: `msg${i}` })
        ids.push(store.getState().messages[i].id)
      }

      const firstPage = store.page({ limit: 2 })
      const secondPage = store.page({ limit: 2, before: firstPage[firstPage.length - 1].id })

      expect(firstPage).toHaveLength(2)
      expect(secondPage).toHaveLength(2)
      expect(secondPage[0].text).toBe('msg2')
    })

    it('returns empty array if before cursor points to first message', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({ source: 'chat', role: 'user', text: 'only' })
      const firstId = store.getState().messages[0].id

      const result = store.page({ limit: 10, before: firstId })
      expect(result).toEqual([])
    })

    it('defaults to limit 50 if not provided', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      for (let i = 0; i < 100; i++) {
        store.append({ source: 'chat', role: 'user', text: `msg${i}` })
      }

      const result = store.page({})
      expect(result).toHaveLength(50)
    })
  })

  describe('getState', () => {
    it('returns the full thread state', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({ source: 'chat', role: 'user', text: 'msg', sessionId: 'sess-1' })
      store.setCurrentSession('sess-1')

      const state = store.getState()
      expect(state).toHaveProperty('messages')
      expect(state).toHaveProperty('currentSessionId')
      expect(state).toHaveProperty('pendingSummary')
      expect(state).toHaveProperty('sessions')
    })
  })

  describe('hasClientId', () => {
    it('returns true if clientId exists in messages', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'offline',
        role: 'user',
        text: 'message',
        clientId: 'client-abc'
      })

      expect(store.hasClientId('client-abc')).toBe(true)
    })

    it('returns false if clientId does not exist', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'offline',
        role: 'user',
        text: 'message',
        clientId: 'client-abc'
      })

      expect(store.hasClientId('client-xyz')).toBe(false)
    })

    it('survives reload from disk', async () => {
      const filePath = path.join(tempDir, 'thread.json')
      const store1 = createThreadStore({ path: filePath })

      store1.append({
        source: 'offline',
        role: 'user',
        text: 'message',
        clientId: 'client-persisted'
      })

      const store2 = createThreadStore({ path: filePath })
      expect(store2.hasClientId('client-persisted')).toBe(true)
    })
  })

  describe('findByClientId', () => {
    it('returns messages with matching clientId', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'offline',
        role: 'user',
        text: 'message 1',
        clientId: 'client-1'
      })
      store.append({
        source: 'offline',
        role: 'user',
        text: 'message 2',
        clientId: 'client-1'
      })
      store.append({
        source: 'offline',
        role: 'user',
        text: 'message 3',
        clientId: 'client-2'
      })

      const matches = store.findByClientId('client-1')
      expect(matches).toHaveLength(2)
      expect(matches[0].text).toBe('message 1')
      expect(matches[1].text).toBe('message 2')
    })

    it('returns empty array if no matches', async () => {
      const store = createThreadStore({ path: path.join(tempDir, 'thread.json') })

      store.append({
        source: 'offline',
        role: 'user',
        text: 'message',
        clientId: 'client-1'
      })

      const matches = store.findByClientId('client-nonexistent')
      expect(matches).toEqual([])
    })
  })

  describe('thread survival across restarts', () => {
    it('preserves messages, currentSessionId, and sessions through restart', async () => {
      const filePath = path.join(tempDir, 'thread.json')

      // First instance: create thread with messages and state
      const store1 = createThreadStore({ path: filePath })
      store1.append({ source: 'chat', role: 'user', text: 'hello', sessionId: 'sess-1' })
      store1.append({ source: 'chat', role: 'assistant', text: 'hi', sessionId: 'sess-1' })
      store1.setCurrentSession('sess-1')
      store1.rotate({ summary: 'first session', fromSessionId: 'sess-1' })

      // Second instance: open the same file
      const store2 = createThreadStore({ path: filePath })
      const state2 = store2.getState()

      expect(state2.messages).toHaveLength(2)
      expect(state2.messages[0].text).toBe('hello')
      expect(state2.messages[1].text).toBe('hi')
      expect(state2.sessions).toHaveLength(1)
      expect(state2.sessions[0].summary).toBe('first session')
      expect(state2.pendingSummary).toBe('first session')
    })
  })
})
