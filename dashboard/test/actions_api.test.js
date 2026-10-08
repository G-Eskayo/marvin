import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createServer } from 'http'
import { request } from 'http'
import { createActionsApiRouter } from '../mobile-backend/actions_api.js'

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

function makeRequest(baseUrl, method, urlPath, body = null) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, baseUrl)
    const options = {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {}
    }
    const client = request(url, options, (res) => {
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
    })
    client.on('error', reject)
    if (body) {
      client.write(JSON.stringify(body))
    }
    client.end()
  })
}

describe('actions_api', () => {
  describe('POST /boards/ticket/reply', () => {
    it('posts the comment and requeues a waiting ticket on confirmation', async () => {
      const ghCalls = []
      const exec = vi.fn(async (cmd, args) => {
        ghCalls.push(args)
        if (args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [{ name: 'needs-info' }], state: 'OPEN' }) }
        }
        return { stdout: '' }
      })

      const router = createActionsApiRouter({ exec })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/boards/ticket/reply', {
          repo: 'G-Eskayo/marvin',
          number: 42,
          body: 'Use option B',
          confirmed: true
        })

        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.data.posted).toBe(true)
        expect(res.body.data.requeued).toBe(true)

        // Verify that gh was called for both comment and edit
        expect(ghCalls.some((a) => a[1] === 'comment')).toBe(true)
        expect(ghCalls.some((a) => a[1] === 'edit')).toBe(true)
      } finally {
        server.close()
      }
    })

    it('rejects the request without confirmation', async () => {
      const exec = vi.fn()
      const router = createActionsApiRouter({ exec })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/boards/ticket/reply', {
          repo: 'G-Eskayo/marvin',
          number: 42,
          body: 'Use option B',
          confirmed: false
        })

        expect(res.statusCode).toBe(403)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toContain('Action requires confirmation')
        expect(exec).not.toHaveBeenCalled()
      } finally {
        server.close()
      }
    })

    it('rejects missing confirmed field', async () => {
      const exec = vi.fn()
      const router = createActionsApiRouter({ exec })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/boards/ticket/reply', {
          repo: 'G-Eskayo/marvin',
          number: 42,
          body: 'Use option B'
        })

        expect(res.statusCode).toBe(403)
        expect(res.body.ok).toBe(false)
        expect(exec).not.toHaveBeenCalled()
      } finally {
        server.close()
      }
    })

    it('returns 400 on validation error (empty body)', async () => {
      const exec = vi.fn(async () => {
        throw new Error('The comment is empty')
      })
      const router = createActionsApiRouter({ exec })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/boards/ticket/reply', {
          repo: 'G-Eskayo/marvin',
          number: 42,
          body: '',
          confirmed: true
        })

        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toContain('empty')
      } finally {
        server.close()
      }
    })

    it('handles invalid JSON gracefully', async () => {
      const router = createActionsApiRouter({ exec: vi.fn() })
      const { server, url } = await startTestServer(router)
      try {
        const res = await new Promise((resolve, reject) => {
          const urlObj = new URL('/boards/ticket/reply', url)
          const client = request(urlObj, { method: 'POST' }, (res) => {
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
          })
          client.on('error', reject)
          client.write('not json')
          client.end()
        })

        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toContain('Invalid JSON')
      } finally {
        server.close()
      }
    })
  })

  describe('POST /mr/approve', () => {
    it('posts the PR URL to the webhook on confirmation', async () => {
      const post = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ merged: true, reengaged: false, reason: null })
      })
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/approve', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          confirmed: true
        })

        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.data.merged).toBe(true)
        expect(post).toHaveBeenCalledWith(
          expect.stringContaining('7878/approve'),
          { pr_url: 'https://github.com/G-Eskayo/marvin/pull/71' }
        )
      } finally {
        server.close()
      }
    })

    it('rejects the request without confirmation', async () => {
      const post = vi.fn()
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/approve', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          confirmed: false
        })

        expect(res.statusCode).toBe(403)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toContain('Action requires confirmation')
        expect(post).not.toHaveBeenCalled()
      } finally {
        server.close()
      }
    })

    it('returns 400 on structured webhook failure', async () => {
      const post = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => ({
          code: 'GH_AUTH_INVALID',
          stage: 'merging',
          message: 'Bad credentials'
        })
      })
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/approve', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          confirmed: true
        })

        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
      } finally {
        server.close()
      }
    })

    it('returns 502 when webhook is unreachable', async () => {
      const post = vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => ({})
      })
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/approve', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          confirmed: true
        })

        expect(res.statusCode).toBe(502)
        expect(res.body.ok).toBe(false)
      } finally {
        server.close()
      }
    })
  })

  describe('POST /mr/deny', () => {
    it('posts the deny action and ticket details to the webhook on confirmation', async () => {
      const post = vi.fn().mockResolvedValue({ ok: true, status: 200 })
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/deny', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          ticketNumber: 42,
          action: 'send_feedback',
          reasons: ['Insufficient tests'],
          comment: 'needs more coverage',
          confirmed: true
        })

        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.data.done).toBe(true)
        expect(post).toHaveBeenCalledWith(
          expect.stringContaining('7878/deny'),
          expect.objectContaining({
            action: 'send_feedback',
            pr_url: 'https://github.com/G-Eskayo/marvin/pull/71',
            ticket_number: 42,
            reasons: ['Insufficient tests'],
            comment: 'needs more coverage'
          })
        )
      } finally {
        server.close()
      }
    })

    it('accepts the drop action', async () => {
      const post = vi.fn().mockResolvedValue({ ok: true, status: 200 })
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/deny', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          ticketNumber: 42,
          action: 'drop',
          reasons: ['Out of scope'],
          comment: '',
          confirmed: true
        })

        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
      } finally {
        server.close()
      }
    })

    it('rejects invalid action', async () => {
      const post = vi.fn()
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/deny', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          ticketNumber: 42,
          action: 'invalid',
          reasons: ['test'],
          comment: 'test',
          confirmed: true
        })

        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toContain('Invalid or missing action')
        expect(post).not.toHaveBeenCalled()
      } finally {
        server.close()
      }
    })

    it('rejects the request without confirmation', async () => {
      const post = vi.fn()
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/deny', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          ticketNumber: 42,
          action: 'send_feedback',
          reasons: ['test'],
          comment: 'test',
          confirmed: false
        })

        expect(res.statusCode).toBe(403)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toContain('Action requires confirmation')
        expect(post).not.toHaveBeenCalled()
      } finally {
        server.close()
      }
    })

    it('returns 502 when webhook is unreachable', async () => {
      const post = vi.fn().mockResolvedValue({ ok: false, status: 502 })
      const router = createActionsApiRouter({
        exec: vi.fn(),
        post,
        resolveWebhookHost: () => 'localhost'
      })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/mr/deny', {
          prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
          ticketNumber: 42,
          action: 'send_feedback',
          reasons: ['test'],
          comment: 'test',
          confirmed: true
        })

        expect(res.statusCode).toBe(502)
        expect(res.body.ok).toBe(false)
      } finally {
        server.close()
      }
    })
  })

  describe('unmatched routes', () => {
    it('returns false for unmatched routes', async () => {
      const router = createActionsApiRouter({ exec: vi.fn(), post: vi.fn() })
      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, 'POST', '/unknown-path', {})
        expect(res.statusCode).toBe(404)
      } finally {
        server.close()
      }
    })
  })
})
