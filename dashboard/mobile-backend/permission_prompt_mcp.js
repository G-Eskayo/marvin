#!/usr/bin/env node

// Minimal MCP server for permission prompting: handles tool/call messages from the Claude CLI,
// relays them to a local backend endpoint, and returns the allow/deny decision.
// Runs over stdio with JSON-RPC protocol (hand-rolled for clarity, no SDK dependency).

import http from 'http'

const RELAY_HOST = '127.0.0.1'
const RELAY_PORT = process.env.PERMISSION_RELAY_PORT || 7881
const RELAY_URL = `http://${RELAY_HOST}:${RELAY_PORT}/permission-relay`

let requestId = 0

async function relayToolCall(toolName, input) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      toolName,
      input,
      requestId: `cli-${++requestId}`
    })

    const options = {
      hostname: RELAY_HOST,
      port: RELAY_PORT,
      path: '/permission-relay',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }

    const req = http.request(options, (res) => {
      let data = ''
      res.on('data', (chunk) => {
        data += chunk
      })
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data)
          resolve(parsed)
        } catch (err) {
          reject(new Error(`Failed to parse relay response: ${err.message}`))
        }
      })
    })

    req.on('error', (err) => {
      reject(new Error(`Relay request failed: ${err.message}`))
    })

    req.write(body)
    req.end()
  })
}

function sendJsonRpc(id, result = null, error = null) {
  const response = { jsonrpc: '2.0', id }
  if (error) {
    response.error = { code: -32603, message: error }
  } else {
    response.result = result || {}
  }
  console.log(JSON.stringify(response))
}

async function handleToolCall(req, params) {
  const { name, input } = params
  try {
    const decision = await relayToolCall(name, input)
    sendJsonRpc(req.id, {
      content: [
        {
          type: 'text',
          text: `${decision.behavior === 'allow' ? 'Allowed' : 'Denied'}: ${name}`
        }
      ]
    })
  } catch (err) {
    sendJsonRpc(req.id, null, err.message)
  }
}

async function main() {
  // Read lines from stdin
  const { createInterface } = await import('readline')
  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false
  })

  for await (const line of rl) {
    try {
      const req = JSON.parse(line)

      // MCP init request
      if (req.method === 'initialize') {
        sendJsonRpc(req.id, {
          protocolVersion: '2024-11-05',
          capabilities: {
            tools: {}
          },
          serverInfo: {
            name: 'permission-prompt-mcp',
            version: '1.0.0'
          }
        })
        continue
      }

      // List available tools
      if (req.method === 'tools/list') {
        sendJsonRpc(req.id, { tools: [] })
        continue
      }

      // Handle tool calls
      if (req.method === 'tools/call') {
        await handleToolCall(req, req.params)
        continue
      }

      // Unknown method
      sendJsonRpc(req.id, null, `Unknown method: ${req.method}`)
    } catch (err) {
      console.error(JSON.stringify({
        jsonrpc: '2.0',
        error: { code: -32700, message: `Parse error: ${err.message}` }
      }))
    }
  }
}

main().catch((err) => {
  console.error(JSON.stringify({
    jsonrpc: '2.0',
    error: { code: -32603, message: `Fatal: ${err.message}` }
  }))
  process.exit(1)
})
