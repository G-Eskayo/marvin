import { createServer } from 'http'
import { mergePr } from './merge.js'
import { sendFeedback, dropEntirely } from './deny.js'
import { forwardRefreshPing } from './refresh_relay.js'

const PORT = process.env.PORT || 7878
// The Electron app's own tiny local server (electron/main/index.js),
// separate from this process -- see refresh_relay.js for why the hop
// exists at all.
const DASHBOARD_REFRESH_URL = process.env.MARVIN_DASHBOARD_REFRESH_URL || 'http://localhost:7879/refresh'

function postJson(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = ''
    req.on('data', (chunk) => {
      body += chunk
    })
    req.on('end', () => {
      try {
        resolve(JSON.parse(body))
      } catch {
        reject(new Error('Invalid JSON body'))
      }
    })
  })
}

const server = createServer(async (req, res) => {
  // mr_raiser.py hits this the moment a PR is raised (any machine) so an
  // already-open dashboard on THIS machine refreshes immediately instead
  // of waiting on its own fallback poll. Responds before the forward
  // resolves -- the caller (an autonomous pipeline run) shouldn't wait on
  // whether a dashboard happens to be open here.
  if (req.method === 'POST' && req.url === '/mr-ready') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true }))
    forwardRefreshPing(DASHBOARD_REFRESH_URL, postJson)
    return
  }

  if (req.method !== 'POST' || (req.url !== '/approve' && req.url !== '/deny')) {
    res.writeHead(404).end()
    return
  }

  const isApprove = req.url === '/approve'
  const invalidBodyKey = isApprove ? 'merged' : 'done'

  let payload
  try {
    payload = await readJsonBody(req)
  } catch (err) {
    res.writeHead(400, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ [invalidBodyKey]: false, error: err.message })
    )
    return
  }

  if (isApprove) {
    try {
      await mergePr(payload.pr_url)
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ merged: true }))
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ merged: false, error: String(err.message || err) })
      )
    }
    return
  }

  // req.url === '/deny'
  const { action, pr_url: prUrl, ticket_number: ticketNumber, reasons, comment } = payload
  if (action !== 'send_feedback' && action !== 'drop') {
    res.writeHead(400, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ done: false, error: `Unknown deny action: ${action}` })
    )
    return
  }

  try {
    if (action === 'send_feedback') {
      await sendFeedback({ prUrl, ticketNumber, reasons, comment })
    } else {
      await dropEntirely({ prUrl, ticketNumber })
    }
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ done: true }))
  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ done: false, error: String(err.message || err) })
    )
  }
})

server.listen(PORT, () => {
  console.log(`MR-approval webhook listening on http://localhost:${PORT}/approve`)
})
