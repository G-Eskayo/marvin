import { runSession } from './session_runner.js'

export function createOfflineBatchApiRouter(opts = {}) {
  const runSessionFn = opts.runSession || runSession
  const threadStore = opts.threadStore
  const offlineBatchStore = opts.offlineBatchStore

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /offline-batch with { batchId, exchanges }
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

        const { batchId, exchanges } = payload

        // Validate batchId
        if (!batchId || typeof batchId !== 'string') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid batchId field' })
          )
          return true
        }

        // Validate exchanges
        if (!Array.isArray(exchanges) || exchanges.length === 0) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid exchanges field (must be non-empty array)' })
          )
          return true
        }

        // Validate each exchange shape
        for (const exchange of exchanges) {
          if (!exchange.role || !exchange.text || typeof exchange.role !== 'string' || typeof exchange.text !== 'string') {
            res.writeHead(400, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'Invalid exchange shape (each exchange must have role and text strings)' })
            )
            return true
          }
        }

        try {
          // Check if batch already exists
          let existing = offlineBatchStore.get(batchId)
          let messageIds

          if (existing) {
            // Batch exists
            if (existing.status === 'complete') {
              // Return cached result
              res.writeHead(200, { 'Content-Type': 'application/json' }).end(
                JSON.stringify({
                  ok: true,
                  data: {
                    batchId: existing.batchId,
                    messageIds: existing.messageIds,
                    sessionId: existing.sessionId
                  }
                })
              )
              return true
            }

            // Batch is pending, reuse existing messageIds
            messageIds = existing.messageIds
          } else {
            // New batch: append exchanges to thread store
            messageIds = []
            for (const exchange of exchanges) {
              const message = threadStore.append({
                source: 'offline',
                role: exchange.role,
                text: exchange.text
              })
              messageIds.push(message.id)
            }

            // Create batch record in store
            offlineBatchStore.create(batchId, { messageIds })
          }

          // Build review prompt from exchanges
          const exchangeText = exchanges
            .map(ex => `[${ex.role}]\n${ex.text}`)
            .join('\n\n')

          const reviewPrompt = `The following is an unreviewed batch of exchanges from an offline session. This batch was collected on-device and is now being reviewed for memory preservation and other considerations. Please use your normal judgment about what is worth keeping in memory — no additional actions or replies are expected from you, just your internal judgment applied to this content.\n\n---\n\n${exchangeText}`

          // Run review session
          let resultSessionId = null

          for await (const event of runSessionFn({ exchanges, message: reviewPrompt })) {
            // Capture sessionId from result event
            if (event.type === 'result' && event.sessionId) {
              resultSessionId = event.sessionId
            }
          }

          // If we got a sessionId from the review, backfill it and complete the batch
          if (resultSessionId) {
            // Backfill sessionId onto all appended messages
            for (const messageId of messageIds) {
              threadStore.backfillSession(messageId, resultSessionId)
            }

            // Mark batch as complete
            offlineBatchStore.complete(batchId, { sessionId: resultSessionId })

            res.writeHead(200, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({
                ok: true,
                data: {
                  batchId,
                  messageIds,
                  sessionId: resultSessionId
                }
              })
            )
          } else {
            // No sessionId from review session
            res.writeHead(500, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'Review session did not return a sessionId' })
            )
          }

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
