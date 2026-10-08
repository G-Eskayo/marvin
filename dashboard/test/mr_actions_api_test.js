import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createServer } from 'http'
import { request as httpRequest } from 'http'
import { createMrActionsApiRouter } from '../mobile-backend/mr_actions_api.js'

function startTestServer(router) {
  const server = createServer(async (req, res) => {
    const handled = await router(req, res)
    if (!handled) {
      res.writeHead(404).end()
    }
  })
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      resolve({ server, url: `http://${addr.address}:${addr.port}` })
    })
  })
}

function makeRequest(baseUrl, method, urlPath, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, baseUrl)
    const client = httpRequest(
      url,
      {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : {}
      },
      (res) => {
        let data = ''
        res.on('data', (chunk) => {
          data += chunk
        })
        res.on('end', () => {
          resolve({
            statusCode: res.statusCode,
            body: data ? JSON.parse(data) : null
          })
        })
      }
    )
    client.on('error', reject)
    if (body) {
      client.write(JSON.stringify(body))
    }
    client.end()
  })
}

describe('MR actions API', () => {
  let mockGuardApprove, mockApproveMr, mockDenyMr, mockExec

  beforeEach(() => {
    mockGuardApprove = vi.fn()
    mockApproveMr = vi.fn()
    mockDenyMr = vi.fn()
    mockExec = vi.fn()
  })

  describe('POST /mr/approve', () => {
    it('rejects request without confirmed:true', async () => {
      const router = createMrActionsApiRouter()
      const { server, url } = await startTestServer(router)

      try {
        const res = await makeRequest(url, 'POST', '/mr/approve', {
          url: 'https://github.com/G-Eskayo/marvin/pull/1',
          number: 1,
          confirmed: false
        })
        expect(res.statusCode).toBe(403)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toMatch(/Face ID confirmation/)
      } finally {
        server.close()
      }
    })

    it('rejects request missing confirmed field', async () => {
      const router = createMrActionsApiRouter()
      const { server, url } = await startTestServer(router)

      try {
        const res = await makeRequest(url, 'POST', '/mr/approve', {
          url: 'https://github.com/G-Eskayo/marvin/pull/1',
          number: 1
        })
        expect(res.statusCode).toBe(403)
        expect(res.body.ok).toBe(false)
      } finally {
        server.close()
      }
    })

    it('rejects request with missing required fields', async () => {
      const router = createMrActionsApiRouter()
      const { server, url } = await startTestServer(router)

      try {
        const res = await makeRequest(url, 'POST', '/mr/approve', {
          confirmed: true
        })
        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toMatch(/Missing required fields/)
      } finally {
        server.close()
      }
    })

    it('rejects invalid JSON', async () => {
      const server = createServer(async (req, res) => {
        const router = createMrActionsApiRouter()
        const handled = await router(req, res)
        if (!handled) res.writeHead(404).end()
      })

      return new Promise((resolve) => {
        server.listen(0, '127.0.0.1', async () => {
          const addr = server.address()
          const baseUrl = `http://${addr.address}:${addr.port}`

          try {
            const url = new URL('/mr/approve', baseUrl)
            const client = httpRequest(
              url,
              { method: 'POST', headers: { 'Content-Type': 'application/json' } },
              (res) => {
                let data = ''
                res.on('data', (chunk) => {
                  data += chunk
                })
                res.on('end', () => {
                  const body = JSON.parse(data)
                  expect(res.statusCode).toBe(400)
                  expect(body.ok).toBe(false)
                  expect(body.error).toMatch(/Invalid JSON/)
                  server.close()
                  resolve()
                })
              }
            )
            client.on('error', (err) => {
              server.close()
              resolve(Promise.reject(err))
            })
            client.write('not json')
            client.end()
          } catch (err) {
            server.close()
            resolve(Promise.reject(err))
          }
        })
      })
    })
  })

  describe('POST /mr/deny', () => {
    it('rejects request without confirmed:true', async () => {
      const router = createMrActionsApiRouter()
      const { server, url } = await startTestServer(router)

      try {
        const res = await makeRequest(url, 'POST', '/mr/deny', {
          url: 'https://github.com/G-Eskayo/marvin/pull/1',
          number: 1,
          action: 'send_feedback',
          confirmed: false
        })
        expect(res.statusCode).toBe(403)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toMatch(/Face ID confirmation/)
      } finally {
        server.close()
      }
    })

    it('rejects request with missing required fields', async () => {
      const router = createMrActionsApiRouter()
      const { server, url } = await startTestServer(router)

      try {
        const res = await makeRequest(url, 'POST', '/mr/deny', {
          confirmed: true
        })
        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toMatch(/Missing required fields/)
      } finally {
        server.close()
      }
    })

    it('rejects invalid JSON', async () => {
      const server = createServer(async (req, res) => {
        const router = createMrActionsApiRouter()
        const handled = await router(req, res)
        if (!handled) res.writeHead(404).end()
      })

      return new Promise((resolve) => {
        server.listen(0, '127.0.0.1', async () => {
          const addr = server.address()
          const baseUrl = `http://${addr.address}:${addr.port}`

          try {
            const url = new URL('/mr/deny', baseUrl)
            const client = httpRequest(
              url,
              { method: 'POST', headers: { 'Content-Type': 'application/json' } },
              (res) => {
                let data = ''
                res.on('data', (chunk) => {
                  data += chunk
                })
                res.on('end', () => {
                  const body = JSON.parse(data)
                  expect(res.statusCode).toBe(400)
                  expect(body.ok).toBe(false)
                  expect(body.error).toMatch(/Invalid JSON/)
                  server.close()
                  resolve()
                })
              }
            )
            client.on('error', (err) => {
              server.close()
              resolve(Promise.reject(err))
            })
            client.write('not json')
            client.end()
          } catch (err) {
            server.close()
            resolve(Promise.reject(err))
          }
        })
      })
    })
  })

  it('returns 404 for unmatched routes', async () => {
    const router = createMrActionsApiRouter()
    const { server, url } = await startTestServer(router)

    try {
      const res = await makeRequest(url, 'GET', '/mr/approve', null)
      expect(res.statusCode).toBe(404)
    } finally {
      server.close()
    }
  })
})
