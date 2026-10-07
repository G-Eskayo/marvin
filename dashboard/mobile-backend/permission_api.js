export function createPermissionApiRouter(opts = {}) {
  const pendingActionStore = opts.pendingActionStore

  if (!pendingActionStore) {
    throw new Error('pendingActionStore is required')
  }

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // GET /pending-actions
      if (req.method === 'GET' && pathname === '/pending-actions') {
        const actions = pendingActionStore.list()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: actions })
        )
        return true
      }

      // POST /pending-actions/resolve
      if (req.method === 'POST' && pathname === '/pending-actions/resolve') {
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

        const { id, decision, reason } = payload

        if (!id || typeof id !== 'string') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid id field' })
          )
          return true
        }

        if (!decision || !['allow', 'deny'].includes(decision)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid decision field (must be "allow" or "deny")' })
          )
          return true
        }

        try {
          const action = pendingActionStore.resolve(id, decision, reason || null)
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: action })
          )
        } catch (err) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
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
