import { randomUUID } from 'crypto'

export const DEFAULT_TIMEOUT_MS = 120000

const READ_ONLY_TOOLS = new Set(['read', 'grep', 'glob', 'webfetch', 'websearch'])

export function isReadOnlyTool(toolName) {
  return READ_ONLY_TOOLS.has(toolName.toLowerCase())
}

export function summarize(toolName, toolInput) {
  const input = toolInput || {}

  if (toolName.toLowerCase() === 'bash') {
    const cmd = input.command || ''
    const truncated = cmd.length > 50 ? cmd.substring(0, 47) + '...' : cmd
    return `Run: \`${truncated}\``
  }

  if (toolName.toLowerCase() === 'edit') {
    const file = input.file_path || '(file)'
    const basename = file.split('/').pop()
    return `Edit ${basename}`
  }

  if (toolName.toLowerCase() === 'write') {
    const file = input.file_path || '(file)'
    const basename = file.split('/').pop()
    return `Write ${basename}`
  }

  return `Use ${toolName}`
}

export function createPendingActionStore() {
  const actions = new Map()

  return {
    create(toolName, toolInput, summary) {
      const id = randomUUID()
      const action = {
        id,
        toolName,
        toolInput,
        summary,
        status: 'pending',
        createdAt: new Date()
      }
      actions.set(id, action)
      return action
    },

    get(id) {
      return actions.get(id) || null
    },

    list() {
      return Array.from(actions.values()).filter(a => a.status === 'pending')
    },

    resolve(id, decision) {
      const action = actions.get(id)
      if (!action) return null

      action.status = decision
      action.resolvedAt = new Date()
      return action
    }
  }
}

export async function requestPermission(toolName, toolInput, opts = {}) {
  const { store, timeoutMs } = opts
  const timeout = timeoutMs !== undefined ? timeoutMs : DEFAULT_TIMEOUT_MS

  // Read-only tools bypass pending action entirely
  if (isReadOnlyTool(toolName)) {
    return { decision: 'allow' }
  }

  // Side-effecting tools: create pending action and wait for resolution
  const actualStore = store || createPendingActionStore()
  const summary = summarize(toolName, toolInput)
  const action = actualStore.create(toolName, toolInput, summary)

  return new Promise((resolve) => {
    const timeoutHandle = setTimeout(() => {
      actualStore.resolve(action.id, 'timed_out')
      resolve({ decision: 'deny', reason: 'timed_out', actionId: action.id })
    }, timeout)

    // Poll for resolution every 10ms (simple approach for testing)
    const pollHandle = setInterval(() => {
      const current = actualStore.get(action.id)
      if (current && current.status !== 'pending') {
        clearInterval(pollHandle)
        clearTimeout(timeoutHandle)
        const decision = current.status === 'approved' ? 'allow' : 'deny'
        const reason = current.status === 'denied' ? 'denied' : undefined
        resolve({ decision, reason, actionId: action.id })
      }
    }, 10)
  })
}
