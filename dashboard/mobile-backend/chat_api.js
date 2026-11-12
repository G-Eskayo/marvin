import { runSession } from './session_runner.js'
import { shouldRotate, summarize } from './rotation_policy.js'
import { execSync } from 'child_process'

export function createChatApiRouter(opts = {}) {
  const runSessionFn = opts.runSession || runSession
  const threadStore = opts.threadStore
  const execFn = opts.exec || execSync

  // Resolve the model for a task via route.py when there's no current session
  function resolveModel(taskDescription) {
    try {
      const venvPython = `${process.env.HOME}/.agents/venv/bin/python`
      const routeScript = `${process.env.HOME}/.agents/skills/route/scripts/route.py`
      const output = execFn(
        `${venvPython} ${routeScript} --model-for-launch "${taskDescription.replace(/"/g, '\\"')}"`,
        { encoding: 'utf-8', timeout: 5000 }
      ).trim()
      return output || null
    } catch (err) {
      // Fail open: if route.py errors or times out, return null (use default model)
      return null
    }
  }

  // Handler for chat API routes
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /chat with { message }
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

        const { message } = payload
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

        try {
          // Get current session and pending summary
          const currentSessionId = threadStore.currentSession()
          const pendingSummary = threadStore.getState().pendingSummary

          // Construct the outgoing message, prepending summary if present
          let outgoingMessage = message
          if (pendingSummary) {
            outgoingMessage = `${pendingSummary}\n\n${message}`
          }

          // Append user message to thread store (sessionId may be backfilled later)
          const userMessageId = threadStore.append({
            source: 'chat',
            role: 'user',
            text: message
          }).id

          let resultSessionId = null
          let assistantText = ''

          // Resolve model for new sessions
          const runSessionOpts = { message: outgoingMessage, sessionId: currentSessionId }
          if (!currentSessionId) {
            const resolvedModel = resolveModel(message)
            if (resolvedModel) {
              runSessionOpts.model = resolvedModel
            }
          }

          for await (const event of runSessionFn(runSessionOpts)) {
            // Capture the final sessionId from result events
            if (event.type === 'result' && event.sessionId) {
              resultSessionId = event.sessionId
            }

            // Accumulate assistant text for rotation decision
            if (event.type === 'text') {
              assistantText += event.text
            }

            res.write(JSON.stringify(event) + '\n')
          }

          // Backfill user message sessionId
          if (resultSessionId) {
            threadStore.backfillSession(userMessageId, resultSessionId)

            // Append assistant message
            threadStore.append({
              source: 'chat',
              role: 'assistant',
              text: assistantText,
              sessionId: resultSessionId
            })

            // Set current session
            threadStore.setCurrentSession(resultSessionId)

            // Consume pending summary if present
            threadStore.consumePendingSummary()

            // Check for rotation
            const sessionState = threadStore.getState()
            const sessionMessages = sessionState.messages.filter(m => m.sessionId === resultSessionId)

            const rotationResult = shouldRotate({
              sessionMessages,
              newMessageText: message,
              lengthThreshold: 10,
              topicShiftFn: () => {
                // No topic shift check in base implementation
                return { shift: false }
              }
            })

            if (rotationResult.rotate) {
              const summary = summarize(sessionMessages, { maxLen: 500 })
              threadStore.rotate({
                summary,
                fromSessionId: resultSessionId
              })
            }
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

      // GET /thread?limit=<n>&before=<id>
      if (req.method === 'GET' && pathname === '/thread') {
        const limit = parseInt(url.searchParams.get('limit')) || 50
        const before = url.searchParams.get('before') || null

        try {
          const messages = threadStore.page({ limit, before })
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: messages })
          )
        } catch (err) {
          res.writeHead(500, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: err.message })
          )
        }

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
