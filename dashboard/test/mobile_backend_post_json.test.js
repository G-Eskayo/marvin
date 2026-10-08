import { describe, it, expect, afterEach } from 'vitest'
import { createServer } from 'http'
import { postJson } from '../mobile-backend/post_json.js'

let server

function listen(handler) {
  server = createServer(handler)
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`))
  })
}

afterEach(() => new Promise((resolve) => (server ? server.close(resolve) : resolve())))

describe('postJson', () => {
  it('POSTs the payload as JSON and resolves with the parsed reply', async () => {
    let received
    const base = await listen((req, res) => {
      let body = ''
      req.on('data', (c) => { body += c })
      req.on('end', () => {
        received = { method: req.method, url: req.url, type: req.headers['content-type'], body: JSON.parse(body) }
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ merged: true }))
      })
    })

    const result = await postJson(`${base}/approve?x=1`, { pr_url: 'https://github.com/o/r/pull/1' })

    expect(received).toEqual({
      method: 'POST',
      url: '/approve?x=1',
      type: 'application/json',
      body: { pr_url: 'https://github.com/o/r/pull/1' }
    })
    expect(result.ok).toBe(true)
    expect(result.status).toBe(200)
    expect(await result.json()).toEqual({ merged: true })
  })

  it('reports a non-2xx status and wraps a non-JSON body as an error', async () => {
    const base = await listen((req, res) => {
      req.resume()
      req.on('end', () => res.writeHead(500).end('boom'))
    })

    const result = await postJson(`${base}/deny`, {})

    expect(result.ok).toBe(false)
    expect(result.status).toBe(500)
    expect(await result.json()).toEqual({ error: 'boom' })
  })

  it('rejects when the webhook is unreachable', async () => {
    const base = await listen((req, res) => res.end())
    await new Promise((resolve) => server.close(resolve))
    server = null

    await expect(postJson(`${base}/approve`, {})).rejects.toThrow()
  })
})
