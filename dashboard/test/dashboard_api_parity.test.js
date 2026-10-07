import { describe, it, expect, vi } from 'vitest'
import { createServer } from 'http'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { request } from 'http'
import { recordStage } from '../webhook-server/ticket_stages.js'
import { createDashboardApiRouter } from '../mobile-backend/dashboard_api.js'

function withTempDirs(fn) {
  const root = mkdtempSync(path.join(tmpdir(), 'dashboard-api-test-'))
  const stagesDir = path.join(root, 'ticket-stages')
  const dispatchStatePath = path.join(root, 'dispatch-state.json')
  const healthStatusPath = path.join(root, 'health-status.json')
  const registryPath = path.join(root, 'registry.json')
  const catalogDir = path.join(root, 'catalog')
  const masterDocPath = path.join(root, 'master-doc.md')
  mkdirSync(catalogDir, { recursive: true })
  try {
    return fn({ root, stagesDir, dispatchStatePath, healthStatusPath, registryPath, catalogDir, masterDocPath })
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

describe('dashboard API parity', () => {
  it('GET /activity routes through and returns ok:true', async () =>
    withTempDirs(async (dirs) => {
      writeFileSync(dirs.dispatchStatePath, JSON.stringify({ busy: false }))
      // Don't record any stages - test just that the endpoint exists and returns proper shape

      const router = createDashboardApiRouter({
        stagesDir: dirs.stagesDir,
        dispatchStatePath: dirs.dispatchStatePath,
        healthStatusPath: dirs.healthStatusPath,
        registryPath: dirs.registryPath,
        catalogDir: dirs.catalogDir,
        masterDocPath: dirs.masterDocPath,
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/activity')
        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(Array.isArray(res.body.data)).toBe(true)
      } finally {
        server.close()
      }
    }))

  it('GET /health returns health status', async () =>
    withTempDirs(async (dirs) => {
      const healthData = {
        generated_at: '2026-10-06T00:00:00Z',
        overall: 'green',
        coverage: 100,
        anomaly: null,
        checks: [{ name: 'test', status: 'ok' }]
      }
      writeFileSync(dirs.healthStatusPath, JSON.stringify(healthData))

      const router = createDashboardApiRouter({
        stagesDir: dirs.stagesDir,
        dispatchStatePath: dirs.dispatchStatePath,
        healthStatusPath: dirs.healthStatusPath,
        registryPath: dirs.registryPath,
        catalogDir: dirs.catalogDir,
        masterDocPath: dirs.masterDocPath,
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/health')
        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.data).toHaveProperty('overall')
        expect(res.body.data).toHaveProperty('checks')
      } finally {
        server.close()
      }
    }))

  it('GET /boards returns boards with project status', async () =>
    withTempDirs(async (dirs) => {
      const registryData = {
        boards: [
          { repo: 'G-Eskayo/marvin', label: 'MARVIN', color: '#FF5733' }
        ]
      }
      writeFileSync(dirs.registryPath, JSON.stringify(registryData))

      const router = createDashboardApiRouter({
        stagesDir: dirs.stagesDir,
        dispatchStatePath: dirs.dispatchStatePath,
        healthStatusPath: dirs.healthStatusPath,
        registryPath: dirs.registryPath,
        catalogDir: dirs.catalogDir,
        masterDocPath: dirs.masterDocPath,
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/boards')
        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(Array.isArray(res.body.data)).toBe(true)
        // Status comes from catalog, defaults to 'recent' when catalog is absent
        if (res.body.data.length > 0) {
          expect(['recent', 'active', 'dormant', 'archived']).toContain(res.body.data[0].status)
        }
      } finally {
        server.close()
      }
    }))

  it('GET /boards/ticket requires repo and number parameters', async () =>
    withTempDirs(async (dirs) => {
      const router = createDashboardApiRouter({
        stagesDir: dirs.stagesDir,
        dispatchStatePath: dirs.dispatchStatePath,
        healthStatusPath: dirs.healthStatusPath,
        registryPath: dirs.registryPath,
        catalogDir: dirs.catalogDir,
        masterDocPath: dirs.masterDocPath,
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/boards/ticket')
        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toMatch(/Missing.*parameter/)
      } finally {
        server.close()
      }
    }))

  it('GET /docs/repos returns repos list', async () =>
    withTempDirs(async (dirs) => {
      const mockExec = vi.fn()
      const router = createDashboardApiRouter({
        stagesDir: dirs.stagesDir,
        dispatchStatePath: dirs.dispatchStatePath,
        healthStatusPath: dirs.healthStatusPath,
        registryPath: dirs.registryPath,
        catalogDir: dirs.catalogDir,
        masterDocPath: dirs.masterDocPath,
        deviceId: 'test-device',
        exec: mockExec
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/docs/repos')
        expect(res.statusCode).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.data).toHaveProperty('repos')
        // Should include the master doc at minimum
        expect(res.body.data.repos.some((r) => r.id === '__master__')).toBe(true)
      } finally {
        server.close()
      }
    }))

  it('GET /docs/tree requires id parameter', async () =>
    withTempDirs(async (dirs) => {
      const router = createDashboardApiRouter({
        stagesDir: dirs.stagesDir,
        dispatchStatePath: dirs.dispatchStatePath,
        healthStatusPath: dirs.healthStatusPath,
        registryPath: dirs.registryPath,
        catalogDir: dirs.catalogDir,
        masterDocPath: dirs.masterDocPath,
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/docs/tree')
        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toMatch(/Missing.*id/)
      } finally {
        server.close()
      }
    }))

  it('GET /docs/content requires id and path parameters', async () =>
    withTempDirs(async (dirs) => {
      const router = createDashboardApiRouter({
        stagesDir: dirs.stagesDir,
        dispatchStatePath: dirs.dispatchStatePath,
        healthStatusPath: dirs.healthStatusPath,
        registryPath: dirs.registryPath,
        catalogDir: dirs.catalogDir,
        masterDocPath: dirs.masterDocPath,
        deviceId: 'test-device',
        exec: vi.fn()
      })

      const { server, url } = await startTestServer(router)
      try {
        const res = await makeRequest(url, '/docs/content?id=test')
        expect(res.statusCode).toBe(400)
        expect(res.body.ok).toBe(false)
        expect(res.body.error).toMatch(/Missing.*path/)
      } finally {
        server.close()
      }
    }))
})
