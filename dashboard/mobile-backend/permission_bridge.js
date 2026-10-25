// Permission bridge: gates side-effecting tool calls via pending actions.
// Fixes prior MCP attempt: uses real setTimeout timers, not lazy eviction.

const READ_ONLY_TOOLS = new Set(['Read', 'Grep', 'Glob', 'WebSearch'])

// Classify a tool as read-only or side-effecting.
export function classifyTool(toolName) {
  return READ_ONLY_TOOLS.has(toolName) ? 'read' : 'side-effecting'
}

// Create a short summary of a tool call for the pending action UI.
export function summarize(toolName, toolInput) {
  if (!toolInput) return toolName

  switch (toolName) {
    case 'Bash':
      const cmd = toolInput.command || ''
      return `Bash: ${cmd.substring(0, 60)}${cmd.length > 60 ? '…' : ''}`

    case 'Edit':
    case 'Write':
      const file = toolInput.file_path || toolInput.filePath || ''
      return `${toolName}: ${file}`

    case 'WebFetch':
      const url = toolInput.url || ''
      return `Fetch: ${url.substring(0, 50)}${url.length > 50 ? '…' : ''}`

    case 'WebSearch':
      const query = toolInput.query || ''
      return `Search: ${query.substring(0, 50)}${query.length > 50 ? '…' : ''}`

    default:
      return toolName
  }
}

// Create a permission bridge that tracks pending actions with real timers.
export function createPermissionBridge(opts = {}) {
  const maxPendingMs = opts.maxPendingMs ?? 5 * 60 * 1000 // 5 minutes default

  let nextId = 1
  const pending = new Map()
  const timers = new Map()

  return {
    // Request permission for a tool call. Read-only tools auto-allow.
    // Returns { id, behavior: 'allow'|'pending' }.
    requestPermission(toolName, toolInput) {
      if (classifyTool(toolName) === 'read') {
        return { id: null, behavior: 'allow' }
      }

      const id = String(nextId++)
      const summary = summarize(toolName, toolInput)

      const promise = new Promise((resolve) => {
        pending.set(id, { summary, toolName, toolInput, resolve, settled: false })

        // Schedule auto-deny on timeout
        const timer = setTimeout(() => {
          if (pending.has(id)) {
            const entry = pending.get(id)
            if (!entry.settled) {
              entry.settled = true
              entry.resolvedAt = Date.now()
              entry.resolve(false) // deny
              timers.delete(id)
            }
          }
        }, maxPendingMs)

        timers.set(id, timer)
      })

      return { id, behavior: 'pending', promise }
    },

    // Resolve a pending action by ID with allow (true) or deny (false).
    resolve(id, decision) {
      if (!pending.has(id)) {
        throw new Error(`Unknown pending action: ${id}`)
      }

      const entry = pending.get(id)
      if (entry.settled) {
        throw new Error(`Pending action already resolved: ${id}`)
      }

      entry.settled = true
      entry.resolvedAt = Date.now()
      entry.resolve(!!decision)

      const timer = timers.get(id)
      if (timer) {
        clearTimeout(timer)
        timers.delete(id)
      }

      // Keep entry in pending for double-resolve detection, will be cleaned up
      // when the next list() is called. This prevents memory bloat while
      // catching double-resolve bugs.
    },

    // List all pending actions. Skips settled entries but keeps them for double-resolve detection.
    list() {
      const result = []
      const toDelete = []
      for (const [id, entry] of pending.entries()) {
        if (!entry.settled) {
          result.push({
            id,
            summary: entry.summary,
            toolName: entry.toolName
          })
        } else {
          // Mark settled entries older than 1 minute for cleanup
          const age = Date.now() - (entry.resolvedAt || 0)
          if (age > 60000) {
            toDelete.push(id)
          }
        }
      }
      // Clean up old settled entries
      toDelete.forEach(id => pending.delete(id))
      return result
    },

    // Test helper: get raw pending entry (not exported in production).
    _getPending(id) {
      return pending.get(id)
    }
  }
}
