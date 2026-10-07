import { describe, it, expect } from 'vitest'
import { createPermissionApiRouter } from '../mobile-backend/permission_api.js'
import { createPermissionBridge } from '../mobile-backend/permission_bridge.js'

// Helper to simulate HTTP request/response
function makeReq(method, url, body = null) {
  const chunks = []
  let ended = false

  return {
    method,
    url,
    headers: { host: 'localhost' },
    [Symbol.asyncIterator]: async function* () {
      if (body !== null) {
        yield Buffer.from(JSON.stringify(body), 'utf-8')
      }
    },
    write(data) {
      chunks.push(data)
      return this
    },
    writeHead(code, headers) {
      this._statusCode = code
      this._headers = headers
      return this
    },
    end(data) {
      if (data) chunks.push(data)
      ended = true
      return this
    },
    _getBody() {
      return chunks.join('')
    }
  }
}

describe('permission API router', () => {
  it('throws if bridge option is missing', () => {
    expect(() => createPermissionApiRouter({})).toThrow('bridge option')
  })

  describe('GET /pending-actions', () => {
    it('returns empty actions list initially', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })
      const req = makeReq('GET', '/pending-actions')

      const handled = await router(req, req)
      expect(handled).toBe(true)
      expect(req._statusCode).toBe(200)

      const body = JSON.parse(req._getBody())
      expect(body).toEqual({ ok: true, actions: [] })
    })

    it('returns pending actions', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      })

      const req = makeReq('GET', '/pending-actions')
      const handled = await router(req, req)
      expect(handled).toBe(true)

      const body = JSON.parse(req._getBody())
      expect(body.ok).toBe(true)
      expect(body.actions).toHaveLength(1)
      expect(body.actions[0]).toMatchObject({
        id: expect.stringMatching(/^perm_\d+$/),
        toolName: 'Bash',
        summary: 'Run: ls',
        requestId: 'req-1'
      })
    })
  })

  describe('POST /pending-actions/resolve', () => {
    it('approves a pending action', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      })

      const [action] = bridge.list()
      const req = makeReq('POST', '/pending-actions/resolve', {
        id: action.id,
        decision: true
      })

      const handled = await router(req, req)
      expect(handled).toBe(true)
      expect(req._statusCode).toBe(200)

      const body = JSON.parse(req._getBody())
      expect(body).toEqual({ ok: true })
      expect(bridge.list()).toHaveLength(0)
    })

    it('denies a pending action', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      bridge.requestPermission({
        toolName: 'Write',
        input: { file_path: '/etc/passwd' },
        requestId: 'req-1'
      })

      const [action] = bridge.list()
      const req = makeReq('POST', '/pending-actions/resolve', {
        id: action.id,
        decision: false
      })

      const handled = await router(req, req)
      expect(handled).toBe(true)

      const body = JSON.parse(req._getBody())
      expect(body).toEqual({ ok: true })
      expect(bridge.list()).toHaveLength(0)
    })

    it('returns false for unknown action', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      const req = makeReq('POST', '/pending-actions/resolve', {
        id: 'perm_unknown',
        decision: true
      })

      const handled = await router(req, req)
      expect(handled).toBe(true)
      expect(req._statusCode).toBe(200)

      const body = JSON.parse(req._getBody())
      expect(body).toEqual({ ok: false })
    })

    it('validates id field', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      const req = makeReq('POST', '/pending-actions/resolve', {
        decision: true
      })

      const handled = await router(req, req)
      expect(handled).toBe(true)
      expect(req._statusCode).toBe(400)

      const body = JSON.parse(req._getBody())
      expect(body.ok).toBe(false)
      expect(body.error).toMatch(/id/)
    })

    it('validates decision field is boolean', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      })

      const [action] = bridge.list()
      const req = makeReq('POST', '/pending-actions/resolve', {
        id: action.id,
        decision: 'yes'
      })

      const handled = await router(req, req)
      expect(handled).toBe(true)
      expect(req._statusCode).toBe(400)

      const body = JSON.parse(req._getBody())
      expect(body.ok).toBe(false)
      expect(body.error).toMatch(/decision/)
    })

    it('returns 400 on invalid JSON', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      // Manually create a request with invalid JSON
      const chunks = []
      const req = {
        method: 'POST',
        url: '/pending-actions/resolve',
        headers: { host: 'localhost' },
        [Symbol.asyncIterator]: async function* () {
          yield Buffer.from('not json', 'utf-8')
        },
        write(data) {
          chunks.push(data)
          return this
        },
        writeHead(code, headers) {
          this._statusCode = code
          this._headers = headers
          return this
        },
        end(data) {
          if (data) chunks.push(data)
          return this
        },
        _getBody() {
          return chunks.join('')
        }
      }

      const handled = await router(req, req)
      expect(handled).toBe(true)
      expect(req._statusCode).toBe(400)

      const body = JSON.parse(req._getBody())
      expect(body.ok).toBe(false)
    })
  })

  describe('unknown routes', () => {
    it('returns false for unmatched routes', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      const req = makeReq('GET', '/unknown')
      const handled = await router(req, req)
      expect(handled).toBe(false)
    })

    it('returns false for non-matching methods', async () => {
      const bridge = createPermissionBridge()
      const router = createPermissionApiRouter({ bridge })

      const req = makeReq('DELETE', '/pending-actions')
      const handled = await router(req, req)
      expect(handled).toBe(false)
    })
  })
})
