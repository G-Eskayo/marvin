import { readFileSync, writeFileSync, existsSync } from 'fs'

export function createOfflineBatchStore(opts = {}) {
  const filePath = opts.path || `${process.env.HOME}/.claude/mobile-offline-batches.json`

  function loadState() {
    if (existsSync(filePath)) {
      try {
        const data = readFileSync(filePath, 'utf-8')
        return JSON.parse(data)
      } catch (err) {
        console.error(`Failed to load offline batch store from ${filePath}:`, err.message)
        return { batches: [] }
      }
    }
    return { batches: [] }
  }

  function persist(state) {
    writeFileSync(filePath, JSON.stringify(state, null, 2))
  }

  return {
    create(batchId, { messageIds }) {
      const state = loadState()
      const batch = {
        batchId,
        messageIds,
        sessionId: null,
        status: 'pending',
        createdAt: Date.now()
      }
      state.batches.push(batch)
      persist(state)
      return batch
    },

    get(batchId) {
      const state = loadState()
      return state.batches.find(b => b.batchId === batchId) || null
    },

    complete(batchId, { sessionId }) {
      const state = loadState()
      const batch = state.batches.find(b => b.batchId === batchId)

      if (!batch) {
        throw new Error(`Batch not found: ${batchId}`)
      }

      if (batch.status !== 'pending') {
        throw new Error(`Batch is already complete: ${batchId}`)
      }

      batch.status = 'complete'
      batch.sessionId = sessionId
      batch.completedAt = Date.now()

      persist(state)
      return batch
    }
  }
}
