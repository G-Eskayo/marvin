import { runSession } from './session_runner.js'
import { shouldRotate, summarize } from './rotation_policy.js'

export function createOfflineBatchApiRouter(opts = {}) {
  const runSessionFn = opts.runSession || runSession
  const threadStore = opts.threadStore

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /offline-batch with { exchanges: [{ clientId, role, text, ts }] }
      if (req.method === 'POST' && pathname === '/offline-batch') {
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

        const { exchanges } = payload
        if (!Array.isArray(exchanges)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'exchanges must be an array' })
          )
          return true
        }

        if (exchanges.length === 0) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'exchanges array cannot be empty' })
          )
          return true
        }

        // Validate each exchange
        for (let i = 0; i < exchanges.length; i++) {
          const ex = exchanges[i]
          if (!ex.clientId || typeof ex.clientId !== 'string') {
            res.writeHead(400, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: `Exchange ${i}: missing or invalid clientId` })
            )
            return true
          }
          if (!ex.role || typeof ex.role !== 'string' || !['user', 'assistant'].includes(ex.role)) {
            res.writeHead(400, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: `Exchange ${i}: missing or invalid role (must be 'user' or 'assistant')` })
            )
            return true
          }
          if (!ex.text || typeof ex.text !== 'string') {
            res.writeHead(400, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: `Exchange ${i}: missing or invalid text` })
            )
            return true
          }
        }

        try {
          // Dedupe: identify which exchanges are already in the store
          const skipped = []
          const toAdd = []

          for (const ex of exchanges) {
            if (threadStore.findByClientId(ex.clientId)) {
              skipped.push(ex.clientId)
            } else {
              toAdd.push(ex)
            }
          }

          // If nothing new, return immediately
          if (toAdd.length === 0) {
            res.writeHead(200, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({
                ok: true,
                data: {
                  added: [],
                  skipped,
                  reviewed: false
                }
              })
            )
            return true
          }

          // Append new exchanges to thread store
          const addedIds = []
          for (const ex of toAdd) {
            const message = threadStore.append({
              source: 'offline',
              role: ex.role,
              text: ex.text,
              clientId: ex.clientId,
              ts: ex.ts || Date.now()
            })
            addedIds.push(message.id)
          }

          // Build review prompt from only the newly-added exchanges
          const reviewPrompt = buildReviewPrompt(toAdd)

          // Get current session and run review through runSession
          const currentSessionId = threadStore.currentSession()
          let resultSessionId = null
          let reviewText = ''

          for await (const event of runSessionFn({ message: reviewPrompt, sessionId: currentSessionId })) {
            // Capture the final sessionId from result events
            if (event.type === 'result' && event.sessionId) {
              resultSessionId = event.sessionId
            }

            // Accumulate review text
            if (event.type === 'text') {
              reviewText += event.text
            }
          }

          // Backfill sessionId on the newly-added offline messages
          if (resultSessionId) {
            for (const messageId of addedIds) {
              threadStore.backfillSession(messageId, resultSessionId)
            }

            // Set current session
            threadStore.setCurrentSession(resultSessionId)

            // Check for rotation
            const sessionState = threadStore.getState()
            const sessionMessages = sessionState.messages.filter(m => m.sessionId === resultSessionId)

            const rotationResult = shouldRotate({
              sessionMessages,
              newMessageText: reviewPrompt,
              lengthThreshold: 10,
              topicShiftFn: () => {
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

          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({
              ok: true,
              data: {
                added: addedIds,
                skipped,
                reviewed: true
              }
            })
          )
          return true
        } catch (err) {
          res.writeHead(500, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: err.message })
          )
          return true
        }
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

// Build a review prompt from offline exchanges
function buildReviewPrompt(exchanges) {
  const exchangeText = exchanges
    .map(ex => `${ex.role}: ${ex.text}`)
    .join('\n')

  return `Review and curate the following offline exchanges for memory:

${exchangeText}

Decide what insights, decisions, or context are worth saving to long-term memory. If anything is noteworthy, document it concisely.`
}
