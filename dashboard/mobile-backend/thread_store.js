import { readFileSync, writeFileSync, existsSync } from 'fs'
import { randomUUID } from 'crypto'

export function createThreadStore(opts = {}) {
  const filePath = opts.path || `${process.env.HOME}/.claude/mobile-thread.json`

  // Load or initialize state
  let state = {
    messages: [],
    currentSessionId: null,
    pendingSummary: null,
    sessions: []
  }

  if (existsSync(filePath)) {
    try {
      const data = readFileSync(filePath, 'utf-8')
      state = JSON.parse(data)
    } catch (err) {
      console.error(`Failed to load thread store from ${filePath}:`, err.message)
    }
  }

  // Persist state to disk synchronously
  function persist() {
    writeFileSync(filePath, JSON.stringify(state, null, 2))
  }

  return {
    append({ source, role, text, sessionId = null }) {
      // Validate source
      const validSources = ['chat', 'voice', 'proactive', 'offline']
      if (!validSources.includes(source)) {
        throw new Error(`source must be one of ${validSources.join(', ')}`)
      }

      const message = {
        id: randomUUID(),
        source,
        role,
        text,
        sessionId,
        ts: Date.now()
      }

      state.messages.push(message)
      persist()
      return message
    },

    backfillSession(messageId, sessionId) {
      const message = state.messages.find(m => m.id === messageId)
      if (!message) {
        throw new Error(`Message not found: ${messageId}`)
      }

      message.sessionId = sessionId
      persist()
    },

    currentSession() {
      return state.currentSessionId
    },

    setCurrentSession(sessionId) {
      state.currentSessionId = sessionId
      persist()
    },

    rotate({ summary, fromSessionId }) {
      // Archive the session
      state.sessions.push({
        sessionId: fromSessionId,
        summary,
        endedAt: Date.now()
      })

      // Clear current session and set pending summary
      state.currentSessionId = null
      state.pendingSummary = summary

      persist()
    },

    consumePendingSummary() {
      const summary = state.pendingSummary
      if (summary) {
        state.pendingSummary = null
        persist()
      }
      return summary
    },

    page({ limit = 50, before = null } = {}) {
      // Find the starting index
      let startIdx = state.messages.length

      if (before) {
        startIdx = state.messages.findIndex(m => m.id === before)
        if (startIdx === -1) {
          // ID not found, return empty
          return []
        }
      }

      // Return messages in reverse order (newest first), up to limit
      const result = []
      for (let i = startIdx - 1; i >= 0 && result.length < limit; i--) {
        result.push(state.messages[i])
      }

      return result
    },

    getState() {
      return state
    }
  }
}
