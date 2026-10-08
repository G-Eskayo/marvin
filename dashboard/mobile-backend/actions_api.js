export function createActionsApiRouter(opts = {}) {
  const postTicketInputFn = opts.postTicketInputFn
  const approveMrFn = opts.approveMrFn
  const denyMrFn = opts.denyMrFn
  const postJson = opts.postJson

  if (!postTicketInputFn || !approveMrFn || !denyMrFn || !postJson) {
    throw new Error('postTicketInputFn, approveMrFn, denyMrFn, and postJson are required')
  }

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /boards/ticket/reply — post a comment on a ticket and re-queue if needed
      if (req.method === 'POST' && pathname === '/boards/ticket/reply') {
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

        const { repo, number, body: commentBody, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Confirmed action required' })
          )
          return true
        }

        try {
          const result = await postTicketInputFn({ repo, number, body: commentBody })
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: result })
          )
        } catch (err) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: err.message })
          )
        }

        return true
      }

      // POST /mr/approve — approve and merge a PR
      if (req.method === 'POST' && pathname === '/mr/approve') {
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

        const { pr_url, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Confirmed action required' })
          )
          return true
        }

        try {
          const result = await approveMrFn(pr_url, postJson)
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: result })
          )
        } catch (err) {
          res.writeHead(500, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: err.message })
          )
        }

        return true
      }

      // POST /mr/deny — deny and send feedback or drop a PR
      if (req.method === 'POST' && pathname === '/mr/deny') {
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

        const { pr_url, ticket_number, action, reasons, comment, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Confirmed action required' })
          )
          return true
        }

        if (!action || !['send_feedback', 'drop'].includes(action)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid action (must be "send_feedback" or "drop")' })
          )
          return true
        }

        try {
          const result = await denyMrFn(
            { prUrl: pr_url, ticketNumber: ticket_number, action, reasons, comment },
            postJson
          )
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: result })
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
