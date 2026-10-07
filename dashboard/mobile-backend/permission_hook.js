import { readFileSync } from 'fs'
import { request } from 'http'
import { homedir } from 'os'
import path from 'path'

export function buildHookOutput(permissionResult, toolName) {
  const decision = permissionResult.decision === 'allow' ? 'allow' : 'deny'
  const reason = decision === 'allow'
    ? `${toolName} is allowed`
    : `${toolName} denied: ${permissionResult.reason || 'user declined'}`

  return JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: decision,
      permissionDecisionReason: reason
    }
  })
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = ''
    process.stdin.setEncoding('utf-8')
    process.stdin.on('data', chunk => {
      data += chunk
    })
    process.stdin.on('end', () => {
      resolve(data)
    })
    process.stdin.on('error', reject)
  })
}

async function main() {
  try {
    const input = await readStdin()
    const { tool_name: toolName, tool_input: toolInput } = JSON.parse(input)

    if (!toolName) {
      console.error('Missing tool_name')
      process.exit(1)
    }

    // Call the internal API on localhost
    const internalPort = process.env.INTERNAL_API_PORT || 3001
    const result = await new Promise((resolve, reject) => {
      const reqOptions = {
        hostname: '127.0.0.1',
        port: internalPort,
        path: '/internal/permission-check',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      }

      const req = request(reqOptions, (res) => {
        let data = ''
        res.on('data', chunk => {
          data += chunk
        })
        res.on('end', () => {
          try {
            resolve(JSON.parse(data))
          } catch {
            reject(new Error('Invalid JSON from internal API'))
          }
        })
      })

      req.on('error', reject)
      req.write(JSON.stringify({ toolName, toolInput }))
      req.end()
    })

    const output = buildHookOutput(result, toolName)
    console.log(output)
  } catch (err) {
    console.error('Hook error:', err.message)
    // Fail safe to deny on error
    const output = buildHookOutput({ decision: 'deny', reason: 'hook_error' }, 'Unknown')
    console.log(output)
    process.exit(1)
  }
}

main()
