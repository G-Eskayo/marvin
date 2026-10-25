import { describe, it, expect, beforeEach } from 'vitest'
import { createPermissionBridge } from '../mobile-backend/permission_bridge.js'
import { createPermissionApiRouter } from '../mobile-backend/permission_api.js'

// Mock req/res for testing
function createMockRequest(method, url, body = null) {
  let currentIndex = 0
  const chunks = body ? [body] : []

  const stream = {
    async *[Symbol.asyncIterator]() {
      for (const chunk of chunks) {
        yield chunk
      }
    }
  }

  return {
    method,
    url,
    headers: { host: 'localhost' },
    [Symbol.asyncIterator]: stream[Symbol.asyncIterator]
  }
}

function createMockResponse() {
  let statusCode = 200
  let headers = {}
  let body = ''

  return {
    writeHead(code, h) {
      statusCode = code
      headers = h
      return this
    },
    write(data) {
      body += data
    },
    end(data) {
      if (data) body += data
    },
    getStatus: () => statusCode,
    getBody: () => body,
    getHeaders: () => headers
  }
}

describe('permission_api', () => {
  let bridge, router

  beforeEach(() => {
    bridge = createPermissionBridge()
    router = createPermissionApiRouter(bridge)
  })

  describe('GET /pending-actions', () => {
    it('returns empty list initially', async () => {
      const req = createMockRequest('GET', 'http://localhost/pending-actions')
      const res = createMockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.getStatus()).toBe(200)

      const data = JSON.parse(res.getBody())
      expect(data.ok).toBe(true)
      expect(data.data).toEqual([])
    })

    it('lists pending actions', async () => {
      bridge.requestPermission('Bash', { command: 'test' })
      bridge.requestPermission('Edit', { file_path: 'file.js' })

      const req = createMockRequest('GET', 'http://localhost/pending-actions')
      const res = createMockResponse()

      await router(req, res)
      const data = JSON.parse(res.getBody())
      expect(data.data).toHaveLength(2)
      expect(data.data[0].toolName).toBe('Bash')
      expect(data.data[1].toolName).toBe('Edit')
    })
  })

  describe('POST /pending-actions/resolve', () => {
    it('resolves a pending action with allow', async () => {
      const { id, promise } = bridge.requestPermission('Bash', {})

      const body = JSON.stringify({ id, decision: true })
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(200)

      const decision = await promise
      expect(decision).toBe(true)
    })

    it('resolves a pending action with deny', async () => {
      const { id, promise } = bridge.requestPermission('Edit', {})

      const body = JSON.stringify({ id, decision: false })
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(200)

      const decision = await promise
      expect(decision).toBe(false)
    })

    it('rejects missing id', async () => {
      const body = JSON.stringify({ decision: true })
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(400)

      const data = JSON.parse(res.getBody())
      expect(data.ok).toBe(false)
      expect(data.error).toContain('id')
    })

    it('rejects invalid id type', async () => {
      const body = JSON.stringify({ id: 123, decision: true })
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(400)
    })

    it('rejects missing decision', async () => {
      const { id } = bridge.requestPermission('Bash', {})

      const body = JSON.stringify({ id })
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(400)

      const data = JSON.parse(res.getBody())
      expect(data.error).toContain('decision')
    })

    it('rejects non-boolean decision', async () => {
      const { id } = bridge.requestPermission('Bash', {})

      const body = JSON.stringify({ id, decision: 'maybe' })
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(400)
    })

    it('rejects unknown action id', async () => {
      const body = JSON.stringify({ id: 'unknown', decision: true })
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(400)

      const data = JSON.parse(res.getBody())
      expect(data.error).toContain('Unknown')
    })

    it('rejects invalid JSON', async () => {
      const body = 'not json'
      const req = createMockRequest('POST', 'http://localhost/pending-actions/resolve', body)
      const res = createMockResponse()

      await router(req, res)
      expect(res.getStatus()).toBe(400)

      const data = JSON.parse(res.getBody())
      expect(data.error).toContain('Invalid JSON')
    })
  })

  describe('unmatched routes', () => {
    it('returns false for unmatched GET', async () => {
      const req = createMockRequest('GET', 'http://localhost/other')
      const res = createMockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for unmatched POST', async () => {
      const req = createMockRequest('POST', 'http://localhost/other', '{}')
      const res = createMockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
