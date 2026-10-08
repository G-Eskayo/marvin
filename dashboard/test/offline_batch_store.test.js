import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createOfflineBatchStore } from '../mobile-backend/offline_batch_store.js'
import { mkdtempSync, rmSync, readFileSync } from 'fs'
import { join } from 'path'
import { tmpdir } from 'os'

describe('offline_batch_store', () => {
  let testDir
  let filePath

  beforeEach(() => {
    testDir = mkdtempSync(join(tmpdir(), 'offline-batch-store-test-'))
    filePath = join(testDir, 'offline-batches.json')
  })

  afterEach(() => {
    rmSync(testDir, { recursive: true })
  })

  describe('create', () => {
    it('creates a new batch record with pending status', () => {
      const store = createOfflineBatchStore({ path: filePath })
      const batch = store.create('batch-123', { messageIds: ['msg-1', 'msg-2'] })

      expect(batch.batchId).toBe('batch-123')
      expect(batch.messageIds).toEqual(['msg-1', 'msg-2'])
      expect(batch.status).toBe('pending')
      expect(batch.sessionId).toBeNull()
      expect(batch.createdAt).toBeDefined()
    })

    it('persists batch to disk', () => {
      const store = createOfflineBatchStore({ path: filePath })
      store.create('batch-456', { messageIds: ['msg-a'] })

      const data = JSON.parse(readFileSync(filePath, 'utf-8'))
      expect(data.batches).toHaveLength(1)
      expect(data.batches[0].batchId).toBe('batch-456')
    })
  })

  describe('get', () => {
    it('retrieves a batch by ID', () => {
      const store = createOfflineBatchStore({ path: filePath })
      store.create('batch-789', { messageIds: ['msg-x'] })

      const batch = store.get('batch-789')
      expect(batch).toBeDefined()
      expect(batch.batchId).toBe('batch-789')
      expect(batch.messageIds).toEqual(['msg-x'])
    })

    it('returns null for non-existent batch', () => {
      const store = createOfflineBatchStore({ path: filePath })
      expect(store.get('nonexistent')).toBeNull()
    })

    it('reflects disk changes when reading from separate store instance', () => {
      const store1 = createOfflineBatchStore({ path: filePath })
      store1.create('batch-shared', { messageIds: ['msg-1', 'msg-2'] })

      const store2 = createOfflineBatchStore({ path: filePath })
      const batch = store2.get('batch-shared')
      expect(batch.batchId).toBe('batch-shared')
      expect(batch.messageIds).toHaveLength(2)
    })
  })

  describe('complete', () => {
    it('transitions batch from pending to complete with sessionId', () => {
      const store = createOfflineBatchStore({ path: filePath })
      store.create('batch-to-complete', { messageIds: ['msg-1'] })

      const completed = store.complete('batch-to-complete', { sessionId: 'sess-abc' })
      expect(completed.status).toBe('complete')
      expect(completed.sessionId).toBe('sess-abc')
      expect(completed.completedAt).toBeDefined()
    })

    it('throws error when completing non-existent batch', () => {
      const store = createOfflineBatchStore({ path: filePath })
      expect(() => store.complete('nonexistent', { sessionId: 'sess-123' })).toThrow('Batch not found')
    })

    it('throws error when completing already-complete batch', () => {
      const store = createOfflineBatchStore({ path: filePath })
      store.create('batch-dup', { messageIds: ['msg-1'] })
      store.complete('batch-dup', { sessionId: 'sess-1' })

      expect(() => store.complete('batch-dup', { sessionId: 'sess-2' })).toThrow('already complete')
    })

    it('persists completion to disk', () => {
      const store = createOfflineBatchStore({ path: filePath })
      store.create('batch-persist', { messageIds: ['msg-1'] })
      store.complete('batch-persist', { sessionId: 'sess-xyz' })

      const data = JSON.parse(readFileSync(filePath, 'utf-8'))
      const batch = data.batches.find(b => b.batchId === 'batch-persist')
      expect(batch.status).toBe('complete')
      expect(batch.sessionId).toBe('sess-xyz')
    })
  })

  describe('persistence across instances', () => {
    it('allows two store instances to see updates from the same file', () => {
      const store1 = createOfflineBatchStore({ path: filePath })
      const store2 = createOfflineBatchStore({ path: filePath })

      store1.create('batch-cross', { messageIds: ['msg-1', 'msg-2'] })
      const retrieved = store2.get('batch-cross')
      expect(retrieved).toBeDefined()

      store2.complete('batch-cross', { sessionId: 'sess-cross' })
      const updated = store1.get('batch-cross')
      expect(updated.status).toBe('complete')
      expect(updated.sessionId).toBe('sess-cross')
    })
  })
})
