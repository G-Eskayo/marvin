import { describe, it, expect, vi } from 'vitest'
import { createServer } from 'http'
import { request } from 'http'
import { readFileSync } from 'fs'
import { mkdtempSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createDashboardApiRouter } from '../mobile-backend/dashboard_api.js'

function withTempDirs(fn) {
  const root = mkdtempSync(path.join(tmpdir(), 'dashboard-scope-test-'))
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

async function makeRequest(baseUrl, urlPath) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, baseUrl)
    const client = request(url, { method: 'GET' }, (res) => {
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

describe('dashboard API scope', () => {
  it('blocks /portfolio routes', async () => {
    return withTempDirs(async () => {
      const router = createDashboardApiRouter({
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/portfolio/components')
        expect(res.statusCode).toBe(404)
      } finally {
        server.close()
      }
    })
  }, 10000)

  it('blocks /profiles routes', async () => {
    return withTempDirs(async () => {
      const router = createDashboardApiRouter({
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/profiles/list')
        expect(res.statusCode).toBe(404)
      } finally {
        server.close()
      }
    })
  }, 10000)

  it('blocks /dispatch routes', async () => {
    return withTempDirs(async () => {
      const router = createDashboardApiRouter({
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/dispatch/status')
        expect(res.statusCode).toBe(404)
      } finally {
        server.close()
      }
    })
  }, 10000)

  it('blocks /boards/load (out of scope)', async () => {
    return withTempDirs(async () => {
      const router = createDashboardApiRouter({
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/boards/load?repo=G-Eskayo/marvin')
        expect(res.statusCode).toBe(404)
      } finally {
        server.close()
      }
    })
  }, 10000)

  it('blocks /docs/search (out of scope)', async () => {
    return withTempDirs(async () => {
      const router = createDashboardApiRouter({
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/docs/search?q=test')
        expect(res.statusCode).toBe(404)
      } finally {
        server.close()
      }
    })
  }, 10000)

  it('does not import electron module', () => {
    const source = readFileSync(
      path.join(path.dirname(__filename), '../mobile-backend/dashboard_api.js'),
      'utf-8'
    )
    expect(source).not.toMatch(/from\s+['"]electron['"]/)
  })

  it('does not import portfolio module', () => {
    const source = readFileSync(
      path.join(path.dirname(__filename), '../mobile-backend/dashboard_api.js'),
      'utf-8'
    )
    expect(source).not.toMatch(/from.*portfolio/)
  })

  it('does not import profiles module', () => {
    const source = readFileSync(
      path.join(path.dirname(__filename), '../mobile-backend/dashboard_api.js'),
      'utf-8'
    )
    expect(source).not.toMatch(/from.*profiles/)
  })

  it('does not import dispatch_status write path', () => {
    const source = readFileSync(
      path.join(path.dirname(__filename), '../mobile-backend/dashboard_api.js'),
      'utf-8'
    )
    // Should not import dispatch_status at all since it's only for writes
    expect(source).not.toMatch(/dispatch_status/)
  })
})
