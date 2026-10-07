import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createPendingActionsStore } from '../mobile-backend/pending_actions.js'
import { mkdtempSync, rmSync, readFileSync } from 'fs'
import { join } from 'path'
import { tmpdir } from 'os'

describe('pending_actions', () => {
  let testDir
  let filePath

  beforeEach(() => {
    testDir = mkdtempSync(join(tmpdir(), 'pending-actions-test-'))
    filePath = join(testDir, 'pending-actions.json')
  })

  afterEach(() => {
    rmSync(testDir, { recursive: true })
  })

  describe('create', () => {
    it('creates a new pending action with a unique ID', () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: { command: 'npm test' },
        summary: 'Run shell command',
        sessionId: 'sess-123'
      })

      expect(action.id).toBeDefined()
      expect(action.toolName).toBe('Bash')
      expect(action.summary).toBe('Run shell command')
      expect(action.status).toBe('pending')
      expect(action.decision).toBeNull()
      expect(action.createdAt).toBeDefined()
      expect(action.resolvedAt).toBeNull()
    })

    it('persists action to disk', () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Edit',
        toolInput: { file_path: 'src/index.js' },
        summary: 'Edit file src/index.js',
        sessionId: 'sess-123'
      })

      const data = JSON.parse(readFileSync(filePath, 'utf-8'))
      expect(data.actions).toHaveLength(1)
      expect(data.actions[0].id).toBe(action.id)
    })
  })

  describe('get', () => {
    it('retrieves an action by ID', () => {
      const store = createPendingActionsStore({ path: filePath })
      const created = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      const retrieved = store.get(created.id)
      expect(retrieved).toEqual(created)
    })

    it('returns null for non-existent action', () => {
      const store = createPendingActionsStore({ path: filePath })
      expect(store.get('non-existent-id')).toBeNull()
    })

    it('reflects disk changes when reading from separate store instance', () => {
      const store1 = createPendingActionsStore({ path: filePath })
      const action = store1.create({
        toolName: 'Write',
        toolInput: { file_path: 'test.txt' },
        summary: 'Write file test.txt',
        sessionId: 'sess-456'
      })

      const store2 = createPendingActionsStore({ path: filePath })
      const retrieved = store2.get(action.id)
      expect(retrieved.id).toBe(action.id)
      expect(retrieved.toolName).toBe('Write')
    })
  })

  describe('list', () => {
    it('returns empty list initially', () => {
      const store = createPendingActionsStore({ path: filePath })
      expect(store.list()).toEqual([])
    })

    it('returns all actions', () => {
      const store = createPendingActionsStore({ path: filePath })
      const action1 = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'cmd1',
        sessionId: null
      })
      const action2 = store.create({
        toolName: 'Edit',
        toolInput: {},
        summary: 'cmd2',
        sessionId: null
      })

      const list = store.list()
      expect(list).toHaveLength(2)
      expect(list[0].id).toBe(action1.id)
      expect(list[1].id).toBe(action2.id)
    })
  })

  describe('resolve', () => {
    it('transitions action from pending to approved', () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      const resolved = store.resolve(action.id, 'allow')
      expect(resolved.status).toBe('approved')
      expect(resolved.decision).toBe('allow')
      expect(resolved.reason).toBeNull()
      expect(resolved.resolvedAt).toBeDefined()
    })

    it('transitions action from pending to denied with reason', () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      const resolved = store.resolve(action.id, 'deny', 'User rejected')
      expect(resolved.status).toBe('denied')
      expect(resolved.decision).toBe('deny')
      expect(resolved.reason).toBe('User rejected')
    })

    it('throws error when resolving non-existent action', () => {
      const store = createPendingActionsStore({ path: filePath })
      expect(() => store.resolve('non-existent-id', 'allow')).toThrow('Action not found')
    })

    it('throws error when resolving already-resolved action', () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      store.resolve(action.id, 'allow')
      expect(() => store.resolve(action.id, 'deny')).toThrow('no longer pending')
    })

    it('persists resolution to disk', () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      store.resolve(action.id, 'allow')

      const data = JSON.parse(readFileSync(filePath, 'utf-8'))
      const resolved = data.actions[0]
      expect(resolved.status).toBe('approved')
      expect(resolved.decision).toBe('allow')
    })
  })

  describe('waitForResolution', () => {
    it('returns immediately if action is already resolved', async () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      store.resolve(action.id, 'allow')
      const resolved = await store.waitForResolution(action.id, { timeoutMs: 1000 })
      expect(resolved.decision).toBe('allow')
    })

    it('waits for resolution when polled concurrently', async () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      const waitPromise = store.waitForResolution(action.id, { timeoutMs: 5000, pollIntervalMs: 50 })

      setTimeout(() => {
        const store2 = createPendingActionsStore({ path: filePath })
        store2.resolve(action.id, 'deny', 'Resolved from another store')
      }, 200)

      const resolved = await waitPromise
      expect(resolved.decision).toBe('deny')
      expect(resolved.reason).toBe('Resolved from another store')
    })

    it('throws error on timeout', async () => {
      const store = createPendingActionsStore({ path: filePath })
      const action = store.create({
        toolName: 'Bash',
        toolInput: {},
        summary: 'test',
        sessionId: null
      })

      await expect(
        store.waitForResolution(action.id, { timeoutMs: 100, pollIntervalMs: 20 })
      ).rejects.toThrow('Timeout waiting for action resolution')
    })

    it('throws error if action not found', async () => {
      const store = createPendingActionsStore({ path: filePath })

      await expect(
        store.waitForResolution('non-existent-id', { timeoutMs: 100 })
      ).rejects.toThrow('Action not found')
    })
  })

  describe('cross-process visibility', () => {
    it('allows two store instances to see updates from the same file', () => {
      const store1 = createPendingActionsStore({ path: filePath })
      const store2 = createPendingActionsStore({ path: filePath })

      const action = store1.create({
        toolName: 'Bash',
        toolInput: { command: 'ls -la' },
        summary: 'List files',
        sessionId: 'sess-789'
      })

      const retrieved = store2.get(action.id)
      expect(retrieved).toBeDefined()
      expect(retrieved.toolName).toBe('Bash')

      store2.resolve(action.id, 'allow')

      const updated = store1.get(action.id)
      expect(updated.decision).toBe('allow')
      expect(updated.status).toBe('approved')
    })
  })
})
