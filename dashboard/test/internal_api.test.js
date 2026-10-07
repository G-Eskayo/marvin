import { describe, it, expect, beforeEach } from 'vitest'
import { createInternalApiRouter } from '../mobile-backend/internal_api.js'
import { createPendingActionStore } from '../mobile-backend/permission_bridge.js'

class MockRequest {
  constructor(method, url, body) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost' }
    this.body = body
    this._index = 0
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

describe('internal_api', () => {
  let store

  beforeEach(() => {
    store = createPendingActionStore()
  })

  describe('POST /internal/permission-check', () => {
    it('immediately approves read-only tools', async () => {
      const router = createInternalApiRouter({ store })
      const req = new MockRequest('POST', '/internal/permission-check', JSON.stringify({
        toolName: 'Read',
        toolInput: { file_path: '/tmp/test' }
      }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      const body = JSON.parse(res.getBody())
      expect(body.decision).toBe('allow')
      expect(body.actionId).toBeUndefined()
    })

    it('creates pending action for side-effecting tools', async () => {
      const router = createInternalApiRouter({ store, timeoutMs: 10000 })
      const req = new MockRequest('POST', '/internal/permission-check', JSON.stringify({
        toolName: 'Bash',
        toolInput: { command: 'ls' }
      }))
      const res = new MockResponse()

      const promise = router(req, res)
      // Give the handler time to create the pending action
      await new Promise(resolve => setTimeout(resolve, 50))
      const actions = store.list()
      expect(actions).toHaveLength(1)
      expect(actions[0].toolName).toBe('Bash')
      // Clean up
      store.resolve(actions[0].id, 'denied')
      await promise
    })

    it('returns 400 for invalid JSON', async () => {
      const router = createInternalApiRouter({ store })
      const req = new MockRequest('POST', '/internal/permission-check', 'not json')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
    })

    it('returns 400 when toolName is missing', async () => {
      const router = createInternalApiRouter({ store })
      const req = new MockRequest('POST', '/internal/permission-check', JSON.stringify({
        toolInput: {}
      }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(400)
    })

    it('returns deny on timeout', async () => {
      const router = createInternalApiRouter({ store, timeoutMs: 50 })
      const req = new MockRequest('POST', '/internal/permission-check', JSON.stringify({
        toolName: 'Bash',
        toolInput: { command: 'test' }
      }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      const body = JSON.parse(res.getBody())
      expect(body.decision).toBe('deny')
      expect(body.reason).toBe('timed_out')
    })
  })

  describe('routing', () => {
    it('returns false for non-matching routes', async () => {
      const router = createInternalApiRouter({ store })
      const req = new MockRequest('GET', '/other', '')
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })

    it('returns false for POST to wrong path', async () => {
      const router = createInternalApiRouter({ store })
      const req = new MockRequest('POST', '/other', JSON.stringify({ toolName: 'Read' }))
      const res = new MockResponse()

      const handled = await router(req, res)
      expect(handled).toBe(false)
    })
  })
})
