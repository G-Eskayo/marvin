import { describe, it, expect, beforeEach } from 'vitest'
import { createPermissionApiRouter } from '../mobile-backend/permission_api.js'
import { createPendingActionStore } from '../mobile-backend/permission_bridge.js'

class MockRequest {
  constructor(method, url, body) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost' }
    this.body = body
  }

  async *[Symbol.asyncIterator]() {
    if (this.body) {
      yield Buffer.from(this.body)
    }
  }
}

class MockResponse {
  constructor() {
    this.statusCode = null
    this.headers = {}
    this.chunks = []
    this.ended = false
  }

  writeHead(statusCode, headers = {}) {
    this.statusCode = statusCode
    this.headers = headers
    return this
  }

  write(chunk) {
    if (typeof chunk === 'string') {
      this.chunks.push(chunk)
    } else {
      this.chunks.push(chunk.toString())
    }
  }

  end(chunk) {
    if (chunk !== undefined) {
      this.write(chunk)
    }
    this.ended = true
  }

  getBody() {
    return this.chunks.join('')
  }
}

describe('permission_api', () => {
  let store

  beforeEach(() => {
    store = createPendingActionStore()
  })

  describe('GET /pending-actions', () => {
    it('returns empty list initially', async () => {
      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('GET', '/pending-actions', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      const body = JSON.parse(res.getBody())
      expect(body.actions).toEqual([])
    })

    it('returns pending actions', async () => {
      const action1 = store.create('Bash', { command: 'test' }, 'Run: `test`')
      const action2 = store.create('Edit', { file_path: 'file.js' }, 'Edit file.js')

      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('GET', '/pending-actions', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      const body = JSON.parse(res.getBody())
      expect(body.actions).toHaveLength(2)
      expect(body.actions[0].id).toBe(action1.id)
      expect(body.actions[1].id).toBe(action2.id)
    })

    it('includes only pending actions, not resolved ones', async () => {
      const action1 = store.create('Bash', { command: 'test' }, 'Run: `test`')
      const action2 = store.create('Edit', { file_path: 'file.js' }, 'Edit file.js')
      store.resolve(action1.id, 'approved')

      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('GET', '/pending-actions', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      const body = JSON.parse(res.getBody())
      expect(body.actions).toHaveLength(1)
      expect(body.actions[0].id).toBe(action2.id)
    })
  })

  describe('POST /pending-actions/:id/approve', () => {
    it('approves a pending action', async () => {
      const action = store.create('Bash', { command: 'test' }, 'Run: `test`')
      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('POST', `/pending-actions/${action.id}/approve`, '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      const body = JSON.parse(res.getBody())
      expect(body.ok).toBe(true)
      expect(store.get(action.id).status).toBe('approved')
    })

    it('returns 404 for unknown action ID', async () => {
      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('POST', '/pending-actions/unknown-id/approve', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(404)
      const body = JSON.parse(res.getBody())
      expect(body.ok).toBe(false)
    })
  })

  describe('POST /pending-actions/:id/deny', () => {
    it('denies a pending action', async () => {
      const action = store.create('Bash', { command: 'test' }, 'Run: `test`')
      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('POST', `/pending-actions/${action.id}/deny`, '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      const body = JSON.parse(res.getBody())
      expect(body.ok).toBe(true)
      expect(store.get(action.id).status).toBe('denied')
    })

    it('returns 404 for unknown action ID', async () => {
      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('POST', '/pending-actions/unknown-id/deny', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(404)
      const body = JSON.parse(res.getBody())
      expect(body.ok).toBe(false)
    })
  })

  describe('routing', () => {
    it('returns false for non-matching routes', async () => {
      const router = createPermissionApiRouter({ store })
      const req = new MockRequest('GET', '/other', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
