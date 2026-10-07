import { readFileSync, writeFileSync, existsSync } from 'fs'
import { randomUUID } from 'crypto'

export function createPendingActionsStore(opts = {}) {
  const filePath = opts.path || `${process.env.HOME}/.claude/mobile-pending-actions.json`

  // Load or initialize state
  function loadState() {
    if (existsSync(filePath)) {
      try {
        const data = readFileSync(filePath, 'utf-8')
        return JSON.parse(data)
      } catch (err) {
        console.error(`Failed to load pending actions from ${filePath}:`, err.message)
        return { actions: [] }
      }
    }
    return { actions: [] }
  }

  // Persist state to disk synchronously
  function persist(state) {
    writeFileSync(filePath, JSON.stringify(state, null, 2))
  }

  return {
    create({ toolName, toolInput, summary, sessionId }) {
      const state = loadState()
      const action = {
        id: randomUUID(),
        toolName,
        toolInput,
        summary,
        sessionId,
        status: 'pending', // 'pending', 'approved', 'denied'
        decision: null, // 'allow', 'deny'
        reason: null,
        createdAt: Date.now(),
        resolvedAt: null
      }
      state.actions.push(action)
      persist(state)
      return action
    },

    get(id) {
      const state = loadState()
      return state.actions.find(a => a.id === id) || null
    },

    list() {
      const state = loadState()
      return state.actions
    },

    resolve(id, decision, reason = null) {
      const state = loadState()
      const action = state.actions.find(a => a.id === id)

      if (!action) {
        throw new Error(`Action not found: ${id}`)
      }

      if (action.status !== 'pending') {
        throw new Error(`Action is no longer pending: ${id}`)
      }

      action.status = decision === 'allow' ? 'approved' : 'denied'
      action.decision = decision
      action.reason = reason
      action.resolvedAt = Date.now()

      persist(state)
      return action
    },

    async waitForResolution(id, opts = {}) {
      const timeoutMs = opts.timeoutMs || 120000
      const pollIntervalMs = opts.pollIntervalMs || 100
      const startTime = Date.now()

      while (Date.now() - startTime < timeoutMs) {
        const action = this.get(id)
        if (!action) {
          throw new Error(`Action not found: ${id}`)
        }

        if (action.status !== 'pending') {
          return action
        }

        await new Promise(resolve => setTimeout(resolve, pollIntervalMs))
      }

      throw new Error(`Timeout waiting for action resolution: ${id}`)
    }
  }
}
