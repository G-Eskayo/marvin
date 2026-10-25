#!/usr/bin/env node
// PreToolUse hook: routes tool requests to the permission relay.
// Fails closed (deny) if relay is unreachable or times out.

import http from 'http'
import { classifyTool } from './permission_bridge.js'

const RELAY_TIMEOUT_MS = 5000

// Make an HTTP request with timeout and return the parsed response body.
export function makeRelayRequest(method, path, bodyObj, timeoutMs = RELAY_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const relayPort = process.env.PERMISSION_RELAY_PORT || 7881
    const bodyStr = bodyObj ? JSON.stringify(bodyObj) : ''
    const options = {
      hostname: '127.0.0.1',
      port: relayPort,
      path,
      method,
      headers: { 'Content-Type': 'application/json' }
    }

    if (bodyStr) {
      options.headers['Content-Length'] = Buffer.byteLength(bodyStr)
    }

    const req = http.request(options, (res) => {
      let data = ''
      res.on('data', (chunk) => {
        data += chunk
      })
      res.on('end', () => {
        try {
          resolve(JSON.parse(data))
        } catch {
          reject(new Error('Invalid JSON response'))
        }
      })
    })

    req.on('error', reject)
    req.setTimeout(timeoutMs, () => {
      req.destroy()
      reject(new Error('Relay timeout'))
    })

    if (bodyStr) {
      req.write(bodyStr)
    }
    req.end()
  })
}

// Determine if a tool call should auto-allow without asking the relay.
export function shouldAutoAllow(toolName) {
  return classifyTool(toolName) === 'read'
}

// Handle a PreToolUse hook invocation.
// Input: stdin with {"tool_name": "...", "tool_input": {...}}
// Output: stdout with {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"|"deny", ...}}
export async function handleHook(input) {
  const { tool_name: toolName, tool_input: toolInput } = input

  // Auto-allow read-only tools
  if (shouldAutoAllow(toolName)) {
    return {
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'allow',
        permissionDecisionReason: 'read-only tool'
      }
    }
  }

  try {
    // Ask the relay for permission
    const response = await makeRelayRequest('POST', '/permission-relay', {
      tool_name: toolName,
      tool_input: toolInput
    })

    return {
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: response.decision ? 'allow' : 'deny',
        permissionDecisionReason: `relay: ${response.reason || 'pending'}`
      }
    }
  } catch (err) {
    // Fail closed: relay unreachable or timeout
    return {
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: `relay error: ${err.message}`
      }
    }
  }
}

// CLI entry point
async function main() {
  try {
    let input = ''
    for await (const chunk of process.stdin) {
      input += chunk.toString()
    }

    const data = JSON.parse(input)
    const decision = await handleHook(data)
    process.stdout.write(JSON.stringify(decision))
  } catch (err) {
    // Fail closed on any error
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: `hook error: ${err.message}`
        }
      })
    )
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    process.stderr.write(`Fatal: ${err.message}\n`)
    process.exit(1)
  })
}
