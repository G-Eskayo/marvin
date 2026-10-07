import { runSession } from './session_runner.js'

// Module-level session ID tracking. Acceptable for #157 (single session, no rotation).
// #158 owns durable persistence and rotation; this stopgap enables streaming.
let currentSessionId = null

// Read JSON body from request, size-limited to prevent abuse.
// Returns parsed JSON or null on error.
async function readJsonBody(req, maxBytes = 1024 * 100) {
  return new Promise((resolve) => {
    let body = ''
    let size = 0

    req.on('data', (chunk) => {
      size += chunk.length
      if (size > maxBytes) {
        req.destroy()
        resolve(null)
        return
      }
      body += chunk.toString()
    })

    req.on('end', () => {
      try {
        resolve(JSON.parse(body))
      } catch {
        resolve(null)
      }
    })

    req.on('error', () => {
      resolve(null)
    })
  })
}

// Handle POST /chat requests. Streams normalised session events as NDJSON.
// Tracks the session ID across requests for resumption (single session, no rotation).
export async function handleChatRequest(req, res, { runSessionFn }) {
  if (req.method !== 'POST' || req.url !== '/chat') {
    res.writeHead(404).end()
    return
  }

  const body = await readJsonBody(req)
  if (!body || typeof body.message !== 'string') {
    res.writeHead(400, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ error: 'invalid request: missing or non-string message field' })
    )
    return
  }

  const message = body.message.trim()
  if (!message) {
    res.writeHead(400, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ error: 'invalid request: message cannot be empty' })
    )
    return
  }

  res.writeHead(200, {
    'Content-Type': 'application/x-ndjson',
    'Transfer-Encoding': 'chunked'
  })

  try {
    const { events, sessionId } = await runSessionFn({
      message,
      sessionId: currentSessionId,
      claudeBin: null // Injected by caller
    })

    // Update session ID for next request.
    currentSessionId = sessionId

    // Stream events as NDJSON.
    for (const event of events) {
      res.write(JSON.stringify(event) + '\n')
    }

    res.end()
  } catch (err) {
    const errorEvent = {
      type: 'error',
      message: err.message || 'Unknown error'
    }
    res.write(JSON.stringify(errorEvent) + '\n')
    res.end()
  }
}

// Inject test/mock runner. For production, pass the real runSession function.
export function createChatHandler(runSessionFn = runSession) {
  return (req, res) => handleChatRequest(req, res, { runSessionFn })
}

// Export session ID tracker for tests.
export function getCurrentSessionId() {
  return currentSessionId
}

export function resetSessionId() {
  currentSessionId = null
}
