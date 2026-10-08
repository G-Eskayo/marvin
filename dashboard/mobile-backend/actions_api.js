import { promisify } from 'util'
import { execFile } from 'child_process'
import { postTicketInput } from '../electron/main/ticket_input.js'
import { approveMr, denyMr } from '../electron/main/mr_review.js'
import { resolveServiceDefaults } from '../electron/main/device_identity.js'

const execFileP = promisify(execFile)

export function createActionsApiRouter(opts = {}) {
  const exec = opts.exec ?? execFileP
  const post = opts.post ?? defaultPost
  const resolveWebhookHost = opts.resolveWebhookHost ?? (() => resolveServiceDefaults().host)

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /boards/ticket/reply
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
            JSON.stringify({ ok: false, error: 'Action requires confirmation' })
          )
          return true
        }

        try {
          const result = await postTicketInput({ repo, number, body: commentBody }, exec)
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

      // POST /mr/approve
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

        const { prUrl, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Action requires confirmation' })
          )
          return true
        }

        try {
          const webhookHost = resolveWebhookHost()
          const webhookUrl = process.env.MARVIN_MR_WEBHOOK_URL || `http://${webhookHost}:7878/approve`
          const result = await approveMr(prUrl, webhookUrl, post)
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: result })
          )
        } catch (err) {
          const statusCode = err.payload?.code ? 400 : 502
          res.writeHead(statusCode, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: err.message })
          )
        }

        return true
      }

      // POST /mr/deny
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

        const { prUrl, ticketNumber, action, reasons, comment, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Action requires confirmation' })
          )
          return true
        }

        if (!action || !['send_feedback', 'drop'].includes(action)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid or missing action field (must be "send_feedback" or "drop")' })
          )
          return true
        }

        try {
          const webhookHost = resolveWebhookHost()
          const webhookUrl = process.env.MARVIN_MR_DENY_WEBHOOK_URL || `http://${webhookHost}:7878/deny`
          await denyMr({ prUrl, ticketNumber, action, reasons, comment }, webhookUrl, post)
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: { done: true } })
          )
        } catch (err) {
          res.writeHead(502, { 'Content-Type': 'application/json' }).end(
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

// Default POST function using fetch
function defaultPost(webhookUrl, body) {
  return fetch(webhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
}
