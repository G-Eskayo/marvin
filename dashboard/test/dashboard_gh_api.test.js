import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createServer } from 'http'
import { request } from 'http'
import { readFileSync, mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createDashboardGhApiRouter } from '../mobile-backend/dashboard_gh_api.js'
import * as boards from '../electron/main/boards.js'

function withTempDirs(fn) {
  const root = mkdtempSync(path.join(tmpdir(), 'dashboard-gh-test-'))
  try {
    return fn({ root })
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
}

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

async function makeRequest(baseUrl, urlPath, method = 'GET') {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, baseUrl)
    const client = request(url, { method }, (res) => {
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
    client.end()
  })
}

describe('dashboard GitHub API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('scope regression', () => {
    it('does not import dispatch_status write path', () => {
      const source = readFileSync(
        path.join(path.dirname(__filename), '../mobile-backend/dashboard_gh_api.js'),
        'utf-8'
      )
      // Should not import writeFileSync from dispatch_status
      expect(source).not.toMatch(/dispatch_status.*write/)
    })

    it('does not import portfolio module', () => {
      const source = readFileSync(
        path.join(path.dirname(__filename), '../mobile-backend/dashboard_gh_api.js'),
        'utf-8'
      )
      expect(source).not.toMatch(/from.*portfolio/)
    })

    it('does not import profiles write path (only read)', () => {
      const source = readFileSync(
        path.join(path.dirname(__filename), '../mobile-backend/dashboard_gh_api.js'),
        'utf-8'
      )
      expect(source).not.toMatch(/setDispatch|setMergeFromDashboard/)
    })
  })

  describe('GET /boards/load', () => {
    it('returns 400 if repo parameter missing', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [] }))

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: vi.fn()
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/boards/load')
            expect(res.statusCode).toBe(400)
            expect(res.body.error).toContain('Missing repo parameter')
          } finally {
            server.close()
          }
        })
      })
    })

    it('returns 400 if repo not in registry', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/clarity-captions', name: 'Clarity Captions' }] }))

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: vi.fn()
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/boards/load?repo=G-Eskayo/unknown')
            expect(res.statusCode).toBe(400)
            expect(res.body.error).toContain('No board registered for G-Eskayo/unknown')
          } finally {
            server.close()
          }
        })
      })
    })
  })

  describe('GET /mr/list', () => {
    it('returns 200 with empty array when no PRs exist', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }] }))

        const execMock = vi.fn((cmd, args) => {
          if (args[0] === 'pr' && args[1] === 'list') {
            return Promise.resolve({ stdout: JSON.stringify([]) })
          }
          if (args[0] === 'issue' && args[1] === 'list') {
            return Promise.resolve({ stdout: JSON.stringify([]) })
          }
          return Promise.reject(new Error('Unexpected call'))
        })

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: execMock
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/list')
            expect(res.statusCode).toBe(200)
            expect(res.body.ok).toBe(true)
            expect(res.body.data).toEqual([])
          } finally {
            server.close()
          }
        })
      })
    })

    it('one repo failure does not hide other repos', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({
          boards: [
            { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
            { repo: 'G-Eskayo/clarity-captions', name: 'Clarity' }
          ]
        }))

        const execMock = vi.fn((cmd, args) => {
          if (args[2] === 'G-Eskayo/clarity-captions') {
            return Promise.reject(new Error('Service unavailable'))
          }
          if (args[0] === 'pr' && args[1] === 'list') {
            return Promise.resolve({ stdout: JSON.stringify([
              { number: 1, title: 'Fix bug', url: 'https://github.com/G-Eskayo/marvin/pull/1', body: '', mergeable: 'MERGEABLE', statusCheckRollup: [] }
            ]) })
          }
          if (args[0] === 'issue' && args[1] === 'list') {
            return Promise.resolve({ stdout: JSON.stringify([]) })
          }
          return Promise.reject(new Error('Unexpected call'))
        })

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: execMock
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/list')
            expect(res.statusCode).toBe(200)
            expect(res.body.ok).toBe(true)
            // Should still get marvin PRs even though clarity failed
            expect(res.body.data.length).toBeGreaterThan(0)
          } finally {
            server.close()
          }
        })
      })
    })
  })

  describe('GET /mr/review-status', () => {
    it('returns green when no open PRs', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }] }))

        const execMock = vi.fn((cmd, args) => {
          if (args[0] === 'pr' && args[1] === 'list') {
            return Promise.resolve({ stdout: JSON.stringify([]) })
          }
          return Promise.reject(new Error('Unexpected call'))
        })

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          mobileSeenPath: path.join(root, 'mr-seen.json'),
          exec: execMock
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/review-status')
            expect(res.statusCode).toBe(200)
            expect(res.body.data.status).toBe('green')
            expect(res.body.data.openCount).toBe(0)
          } finally {
            server.close()
          }
        })
      })
    })

    it('returns red when open PRs unseen', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }] }))

        const seenPath = path.join(root, 'mr-seen.json')
        writeFileSync(seenPath, JSON.stringify({ seen: [] }))

        const execMock = vi.fn((cmd, args) => {
          if (args[0] === 'pr' && args[1] === 'list') {
            return Promise.resolve({ stdout: JSON.stringify([
              { number: 1, title: 'PR 1', url: 'https://github.com/G-Eskayo/marvin/pull/1' }
            ]) })
          }
          return Promise.reject(new Error('Unexpected call'))
        })

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          mobileSeenPath: seenPath,
          exec: execMock
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/review-status')
            expect(res.statusCode).toBe(200)
            expect(res.body.data.status).toBe('red')
            expect(res.body.data.openCount).toBe(1)
          } finally {
            server.close()
          }
        })
      })
    })

    it('handles missing seen file gracefully', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }] }))

        const execMock = vi.fn((cmd, args) => {
          if (args[0] === 'pr' && args[1] === 'list') {
            return Promise.resolve({ stdout: JSON.stringify([
              { number: 1, title: 'PR 1', url: 'https://github.com/G-Eskayo/marvin/pull/1' }
            ]) })
          }
          return Promise.reject(new Error('Unexpected call'))
        })

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          mobileSeenPath: path.join(root, 'nonexistent.json'),
          exec: execMock
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/review-status')
            expect(res.statusCode).toBe(200)
            expect(res.body.ok).toBe(true)
            // Should not crash on missing file
            expect(res.body.data.status).toBe('red')
          } finally {
            server.close()
          }
        })
      })
    })
  })

  describe('GET /mr/ticket-context', () => {
    it('returns 400 if ref parameter missing', async () => {
      const router = createDashboardGhApiRouter({
        exec: vi.fn()
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/mr/ticket-context')
          expect(res.statusCode).toBe(400)
          expect(res.body.error).toContain('Missing ref parameter')
        } finally {
          server.close()
        }
      })
    })

    it('returns 400 if repo not registered and not MARVIN_REPO', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }] }))

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: vi.fn()
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/ticket-context?ref=123&repo=G-Eskayo/unknown')
            expect(res.statusCode).toBe(400)
            expect(res.body.error).toContain('not registered')
          } finally {
            server.close()
          }
        })
      })
    })

    it('returns 200 with ticket and parent when available', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }] }))

        const execMock = vi.fn((cmd, args) => {
          return Promise.resolve({
            stdout: JSON.stringify({
              number: 123,
              title: 'Fix bug',
              body: '## Parent\n\n#456'
            })
          })
        })

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: execMock
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/ticket-context?ref=123')
            expect(res.statusCode).toBe(200)
            expect(res.body.data.ticket.number).toBe(123)
          } finally {
            server.close()
          }
        })
      })
    })

    it('returns null for missing ticket', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }] }))

        const execMock = vi.fn(() => Promise.reject(new Error('Not found')))

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: execMock
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/mr/ticket-context?ref=999')
            expect(res.statusCode).toBe(200)
            expect(res.body.data.ticket).toBeNull()
            expect(res.body.data.parent).toBeNull()
          } finally {
            server.close()
          }
        })
      })
    })
  })

  describe('GET /activity/overview', () => {
    it('returns empty object when no boards', async () => {
      return withTempDirs(({ root }) => {
        const registry = path.join(root, 'registry.json')
        writeFileSync(registry, JSON.stringify({ boards: [] }))

        const router = createDashboardGhApiRouter({
          registryPath: registry,
          exec: vi.fn()
        })

        return startTestServer(router).then(async ({ server, url }) => {
          try {
            const res = await makeRequest(url, '/activity/overview')
            expect(res.statusCode).toBe(200)
            expect(res.body.ok).toBe(true)
            expect(res.body.data).toEqual({})
          } finally {
            server.close()
          }
        })
      })
    })
  })

  describe('GET /relations/ticket', () => {
    it('returns 400 if repo or number missing', async () => {
      const router = createDashboardGhApiRouter({
        exec: vi.fn()
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/relations/ticket?repo=G-Eskayo/marvin')
          expect(res.statusCode).toBe(400)
          expect(res.body.error).toContain('Missing')
        } finally {
          server.close()
        }
      })
    })

    it('returns UNKNOWN state gracefully for non-numeric number', async () => {
      const router = createDashboardGhApiRouter({
        exec: vi.fn()
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/relations/ticket?repo=G-Eskayo/marvin&number=abc')
          expect(res.statusCode).toBe(200)
          expect(res.body.data.state).toBe('UNKNOWN')
          expect(res.body.data.title).toBe('(not loaded)')
        } finally {
          server.close()
        }
      })
    })
  })

  describe('GET /relations/context', () => {
    it('returns 400 if project missing', async () => {
      const router = createDashboardGhApiRouter({
        exec: vi.fn()
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/relations/context')
          expect(res.statusCode).toBe(400)
          expect(res.body.error).toContain('Missing project')
        } finally {
          server.close()
        }
      })
    })

    it('returns project context', async () => {
      const router = createDashboardGhApiRouter({
        exec: vi.fn()
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/relations/context?project=marvin')
          expect(res.statusCode).toBe(200)
          expect(res.body.data.project).toBe('marvin')
          expect(res.body.data.adrs).toBeDefined()
        } finally {
          server.close()
        }
      })
    })
  })

  describe('GET /queue', () => {
    it('handles missing queue service gracefully', async () => {
      const queueRunMock = vi.fn(async () => {
        throw new Error('Queue service unavailable')
      })

      const router = createDashboardGhApiRouter({
        exec: vi.fn(),
        queue: { run: queueRunMock }
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          const res = await makeRequest(url, '/queue')
          expect(res.statusCode).toBe(200)
          expect(res.body.ok).toBe(true)
          expect(res.body.data).toHaveProperty('queue')
          expect(res.body.data).toHaveProperty('running')
          expect(res.body.data).toHaveProperty('error')
        } finally {
          server.close()
        }
      })
    })
  })

  describe('no route matched', () => {
    it('returns false for unknown routes (handled by parent router)', async () => {
      const router = createDashboardGhApiRouter({
        exec: vi.fn()
      })

      return startTestServer(router).then(async ({ server, url }) => {
        try {
          // This should return false from the router, then 404 from the test server
          const res = await makeRequest(url, '/unknown/path')
          expect(res.statusCode).toBe(404)
        } finally {
          server.close()
        }
      })
    })
  })
})
