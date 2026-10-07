#!/usr/bin/env node
import { createPendingActionsStore } from './pending_actions.js'
import { stdin, stdout, env } from 'process'

const READ_ONLY_TOOLS = ['Read', 'Grep', 'Glob', 'WebSearch', 'WebFetch']

function buildSummary(toolName, toolInput) {
  switch (toolName) {
    case 'Read':
      return `Read file: ${toolInput.file_path || 'unknown'}`
    case 'Grep':
      return `Search files: ${toolInput.pattern || 'unknown'}`
    case 'Glob':
      return `Find files: ${toolInput.pattern || 'unknown'}`
    case 'WebSearch':
      return `Web search: ${toolInput.query || 'unknown'}`
    case 'WebFetch':
      return `Fetch URL: ${toolInput.url || 'unknown'}`
    case 'Bash':
      return `Run shell command`
    case 'Edit':
      return `Edit file: ${toolInput.file_path || 'unknown'}`
    case 'Write':
      return `Write file: ${toolInput.file_path || 'unknown'}`
    default:
      return `${toolName} tool call`
  }
}

async function main() {
  const pendingActionPath = env.PENDING_ACTION_PATH || `${process.env.HOME}/.claude/mobile-pending-actions.json`
  const hookTimeoutMs = parseInt(env.HOOK_TIMEOUT_MS || '120000', 10)
  const store = createPendingActionsStore({ path: pendingActionPath })

  let inputData = ''
  for await (const chunk of stdin) {
    inputData += chunk.toString()
  }

  try {
    const payload = JSON.parse(inputData)
    const { tool_name, tool_input, session_id } = payload

    if (!tool_name) {
      stdout.write(JSON.stringify({
        permissionDecision: 'deny',
        reason: 'Missing tool_name in hook input'
      }) + '\n')
      return
    }

    if (READ_ONLY_TOOLS.includes(tool_name)) {
      stdout.write(JSON.stringify({
        permissionDecision: 'allow'
      }) + '\n')
      return
    }

    const summary = buildSummary(tool_name, tool_input || {})
    const action = store.create({
      toolName: tool_name,
      toolInput: tool_input || {},
      summary,
      sessionId: session_id || null
    })

    try {
      await store.waitForResolution(action.id, { timeoutMs: hookTimeoutMs })
      const resolved = store.get(action.id)

      if (resolved.decision === 'allow') {
        stdout.write(JSON.stringify({
          permissionDecision: 'allow'
        }) + '\n')
      } else {
        stdout.write(JSON.stringify({
          permissionDecision: 'deny',
          reason: resolved.reason || 'Denied by user'
        }) + '\n')
      }
    } catch (err) {
      store.resolve(action.id, 'deny', 'Timeout')
      stdout.write(JSON.stringify({
        permissionDecision: 'deny',
        reason: 'Timeout waiting for approval'
      }) + '\n')
    }
  } catch (err) {
    stdout.write(JSON.stringify({
      permissionDecision: 'deny',
      reason: `Hook error: ${err.message}`
    }) + '\n')
  }
}

main().catch(err => {
  stdout.write(JSON.stringify({
    permissionDecision: 'deny',
    reason: `Fatal error: ${err.message}`
  }) + '\n')
})
