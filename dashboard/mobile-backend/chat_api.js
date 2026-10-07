import { runSession } from './session_runner.js'

export function createChatApiRouter(opts = {}) {
  const runSessionFn = opts.runSession || runSession

  // Handler for chat API routes
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /chat with { message, sessionId? }
      if (req.method === 'POST' && pathname === '/chat') {
        // Read body as JSON
        let body = ''
        for await (const chunk of req) {
          body += chunk.toString()
        }

        let payload
        try {
          payload = JSON.parse(body)
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid JSON' })
          )
          return true
        }

        const { message, sessionId } = payload
        if (!message || typeof message !== 'string') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid message field' })
          )
          return true
        }

        // Stream events back as newline-delimited JSON
        res.writeHead(200, {
          'Content-Type': 'application/x-ndjson',
          'Transfer-Encoding': 'chunked'
        })

        let finalSessionId = sessionId
        try {
          for await (const event of runSessionFn({ message, sessionId })) {
            // Capture the final sessionId from result events for the next call
            if (event.type === 'result' && event.sessionId) {
              finalSessionId = event.sessionId
            }
            res.write(JSON.stringify(event) + '\n')
          }
        } catch (err) {
          res.write(JSON.stringify({
            type: 'error',
            message: err.message
          }) + '\n')
        }

        res.end()
        return true
      }

      // No route matched
      return false
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: err.message })
      )
      return true
    }
  }
}
