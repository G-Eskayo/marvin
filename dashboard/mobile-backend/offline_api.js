import { processOfflineBatch } from './offline_batch.js'

export function createOfflineApiRouter(opts = {}) {
  const runSessionFn = opts.runSession || opts.runSessionFn
  const threadStore = opts.threadStore

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /offline-batch with { exchanges: [...] }
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

        try {
          const result = await processOfflineBatch({
            exchanges,
            threadStore,
            runSessionFn
          })

          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({
              ok: result.ok,
              data: {
                appended: result.appended,
                skipped: result.skipped,
                reviewed: result.reviewed,
                sessionId: result.sessionId
              }
            })
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
