// Permission bridge: manages side-effecting tool approval for Claude CLI sessions.
// Maps read-only tools (auto-allow) vs. side-effecting tools (require permission).
// Tracks pending actions and resolves them on permission or timeout.

export function classifyTool(toolName) {
  const readOnlyTools = ['Read', 'Grep', 'Glob', 'WebSearch']
  return readOnlyTools.includes(toolName) ? 'read' : 'side-effecting'
}

export function summarize(toolName, input) {
  switch (toolName) {
    case 'Bash':
      return input?.command ? `Run: ${input.command}` : 'Run a bash command'
    case 'Write':
    case 'Edit':
      return input?.file_path ? `Edit ${input.file_path}` : `Edit a file`
    case 'Read':
      return input?.file_path ? `Read ${input.file_path}` : 'Read a file'
    case 'Grep':
      return input?.pattern ? `Search for ${input.pattern}` : 'Search files'
    case 'Glob':
      return input?.pattern ? `Find files matching ${input.pattern}` : 'Find files'
    case 'WebSearch':
      return input?.query ? `Search: ${input.query}` : 'Search the web'
    case 'WebFetch':
      return input?.url ? `Fetch ${input.url}` : 'Fetch from web'
    default:
      return `Use ${toolName}`
  }
}

export function createPermissionBridge({ maxPendingMs = 120_000 } = {}) {
  const pending = new Map()
  let nextId = 1

  function generateId() {
    return `perm_${nextId++}`
  }

  function live(id, now) {
    const action = pending.get(id)
    if (action && now - action.createdAt > maxPendingMs) {
      pending.delete(id)
      return null
    }
    return action
  }

  return {
    requestPermission({ toolName, input, requestId }, now = Date.now()) {
      const toolClass = classifyTool(toolName)

      if (toolClass === 'read') {
        return Promise.resolve({ behavior: 'allow' })
      }

      const id = generateId()
      pending.set(id, {
        id,
        toolName,
        input,
        summary: summarize(toolName, input),
        createdAt: now,
        requestId,
        resolved: false,
        decision: null
      })

      return new Promise((resolve) => {
        const action = pending.get(id)
        if (action) {
          action.resolve = resolve
        }
      })
    },

    resolve(id, decision, now = Date.now()) {
      const action = live(id, now)
      if (!action || action.resolved) return false

      action.resolved = true
      action.decision = decision

      if (action.resolve) {
        action.resolve({ behavior: decision ? 'allow' : 'deny' })
      }

      pending.delete(id)
      return true
    },

    list(now = Date.now()) {
      const result = []
      for (const [id, action] of pending) {
        if (live(id, now)) {
          result.push({
            id: action.id,
            toolName: action.toolName,
            summary: action.summary,
            createdAt: action.createdAt,
            requestId: action.requestId
          })
        }
      }
      return result
    },

    _internal: {
      pending,
      live
    }
  }
}
