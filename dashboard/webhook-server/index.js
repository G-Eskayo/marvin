import { createServer } from 'http'
import { mergePr } from './merge.js'

const PORT = process.env.PORT || 7878

const server = createServer((req, res) => {
  if (req.method !== 'POST' || req.url !== '/approve') {
    res.writeHead(404).end()
    return
  }

  let body = ''
  req.on('data', (chunk) => {
    body += chunk
  })
  req.on('end', async () => {
    let prUrl
    try {
      prUrl = JSON.parse(body).pr_url
    } catch {
      res.writeHead(400, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ merged: false, error: 'Invalid JSON body' })
      )
      return
    }

    try {
      await mergePr(prUrl)
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ merged: true }))
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ merged: false, error: String(err.message || err) })
      )
    }
  })
})

server.listen(PORT, () => {
  console.log(`MR-approval webhook listening on http://localhost:${PORT}/approve`)
})
