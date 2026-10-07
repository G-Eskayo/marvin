import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createServer } from 'http'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createDashboardApi } from '../mobile-backend/dashboard_api.js'
import { createRequestHandler } from '../mobile-backend/index.js'

describe('createDashboardApi', () => {
  describe('API methods exist', () => {
    it('exposes activityList method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.activityList).toBe('function')
    })

    it('exposes activityTimeline method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.activityTimeline).toBe('function')
    })

    it('exposes healthStatus method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.healthStatus).toBe('function')
    })

    it('exposes boardsList method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.boardsList).toBe('function')
    })

    it('exposes boardsTicket method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.boardsTicket).toBe('function')
    })

    it('exposes docsRepos method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.docsRepos).toBe('function')
    })

    it('exposes docsTree method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.docsTree).toBe('function')
    })

    it('exposes docsContent method', () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      expect(typeof api.docsContent).toBe('function')
    })
  })

  describe('boardsTicket with fetchTicket', () => {
    it('calls gh issue view with correct parameters', async () => {
      let ghCalled = false
      let ghArgs = null
      const mockExec = async (cmd, args) => {
        if (cmd === 'gh') {
          ghCalled = true
          ghArgs = args
          return { stdout: JSON.stringify({ number: 42, title: 'Test ticket' }) }
        }
        throw new Error(`Unexpected exec: ${cmd}`)
      }

      const api = createDashboardApi({ exec: mockExec })
      const result = await api.boardsTicket('G-Eskayo/marvin', 42)

      expect(ghCalled).toBe(true)
      expect(ghArgs).toContain('issue')
      expect(ghArgs).toContain('view')
      expect(ghArgs).toContain('42')
      expect(result.number).toBe(42)
    })

    it('rejects unregistered repos', async () => {
      const mockExec = async () => ({ stdout: '[]' })
      const api = createDashboardApi({ exec: mockExec })

      await expect(api.boardsTicket('unknown/repo', 42)).rejects.toThrow('No board registered')
    })
  })

  describe('docsRepos', () => {
    it('returns structure with repos array', async () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      const result = await api.docsRepos()

      expect(result).toHaveProperty('repos')
      expect(Array.isArray(result.repos)).toBe(true)
    })
  })

  describe('docsTree with MASTER_ID', () => {
    it('returns tree for master docs', async () => {
      const mockExec = async () => ({ stdout: '' })
      const api = createDashboardApi({ exec: mockExec })
      const result = await api.docsTree('__master__')

      expect(result).toHaveProperty('tree')
      expect(Array.isArray(result.tree)).toBe(true)
    })
  })
})

describe('HTTP request handler', () => {
  let server, port

  beforeEach(async () => {
    return new Promise((resolve) => {
      const mockApi = {
        activityList: async () => [{ number: 42, key: 'G-Eskayo/marvin#42' }],
        activityTimeline: async () => [],
        healthStatus: async () => ({ overall: 'green' }),
        boardsList: async () => [],
        boardsTicket: async () => ({ number: 42, title: 'Test' }),
        docsRepos: async () => ({ repos: [] }),
        docsTree: async () => ({ tree: [] }),
        docsContent: async () => 'content'
      }

      const mockWhois = async () => 'test-device'
      const mockLoadAllowlist = () => ['test-device']

      const handler = createRequestHandler({
        dashboardApi: mockApi,
        allowlistPath: '/tmp/allowlist.json',
        whoisFn: mockWhois,
        loadAllowlistFn: mockLoadAllowlist
      })

      server = createServer(handler)
      server.listen(0, '127.0.0.1', () => {
        port = server.address().port
        resolve()
      })
    })
  })

  afterEach(() => {
    return new Promise((resolve) => {
      server.close(resolve)
    })
  })

  it('allows allowlisted peer to access /status', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/status`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.ok).toBe(true)
    expect(data.status).toBe('up')
  })

  it('serves /activity endpoint', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/activity`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
  })

  it('serves /health endpoint', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/health`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.overall).toBe('green')
  })

  it('serves /boards endpoint', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/boards`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
  })

  it('serves /docs/repos endpoint', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/docs/repos`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('repos')
  })

  it('requires number parameter for /activity/timeline', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/activity/timeline`)
    expect(res.status).toBe(400)
    const data = await res.json()
    expect(data.error).toBe('number parameter required')
  })

  it('accepts valid /activity/timeline parameters', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/activity/timeline?number=42&repo=G-Eskayo/marvin`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
  })

  it('requires both repo and number for /boards/ticket', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/boards/ticket`)
    expect(res.status).toBe(400)
  })

  it('accepts valid /boards/ticket parameters', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/boards/ticket?repo=G-Eskayo/marvin&number=42`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.title).toBe('Test')
  })

  it('requires id parameter for /docs/tree', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/docs/tree`)
    expect(res.status).toBe(400)
  })

  it('accepts valid /docs/tree parameters', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/docs/tree?id=marvin`)
    expect(res.status).toBe(200)
  })

  it('requires both id and path for /docs/content', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/docs/content`)
    expect(res.status).toBe(400)
  })

  it('accepts valid /docs/content parameters', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/docs/content?id=marvin&path=CONTEXT.md`)
    expect(res.status).toBe(200)
    const data = await res.text()
    expect(data).toBe('content')
  })

  it('returns 404 for /portfolio routes (out of scope)', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/portfolio/components`)
    expect(res.status).toBe(404)
  })

  it('returns 404 for /profiles routes (out of scope)', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/profiles/list`)
    expect(res.status).toBe(404)
  })

  it('returns 404 for /dispatch routes (out of scope)', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/dispatch/status`)
    expect(res.status).toBe(404)
  })

  it('returns 404 for unknown paths', async () => {
    const res = await fetch(`http://127.0.0.1:${port}/unknown`)
    expect(res.status).toBe(404)
  })
})

describe('IPC parity verification', () => {
  it('dashboard API uses same fetchTicket implementation as Electron', async () => {
    // Both paths should call the same gh issue view with the same JSON fields
    const expectedFields = 'number,title,body,labels,url,state,comments'

    let ghCallArgsCapture = null
    const mockExec = async (cmd, args) => {
      if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
        ghCallArgsCapture = args
      }
      return { stdout: JSON.stringify({ number: 42 }) }
    }

    const api = createDashboardApi({ exec: mockExec })
    await api.boardsTicket('G-Eskayo/marvin', 42)

    // Verify the gh call used the correct fields
    expect(ghCallArgsCapture).toContain('--json')
    expect(ghCallArgsCapture).toContain(expectedFields)
  })
})
