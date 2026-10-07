export function createPermissionApiRouter(opts = {}) {
  const bridge = opts.bridge
  if (!bridge) {
    throw new Error('permission_api requires a bridge option')
  }

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // GET /pending-actions — list all pending permission requests
      if (req.method === 'GET' && pathname === '/pending-actions') {
        const actions = bridge.list()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, actions })
        )
        return true
      }

      // POST /pending-actions/resolve — approve or deny a pending action
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

        const { id, decision } = payload
        if (!id || typeof id !== 'string') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid id field' })
          )
          return true
        }

        if (typeof decision !== 'boolean') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid decision field (must be boolean)' })
          )
          return true
        }

        const success = bridge.resolve(id, decision)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: success })
        )
        return true
      }

      return false
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: err.message })
      )
      return true
    }
  }
}
