import { createServer } from 'http'
import { mergePr } from './merge.js'
import { sendFeedback, dropEntirely } from './deny.js'

const PORT = process.env.PORT || 7878

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
