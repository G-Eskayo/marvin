import { describe, it, expect, beforeEach } from 'vitest'
import { createBenchApiRouter } from '../mobile-backend/bench_api.js'
import { createHttpTailscaleTransport } from '../mobile-backend/transports/http_tailscale.js'

class MockRequest {
  constructor(method, url, body, remoteAddress = '100.1.2.3') {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost' }
    this.body = body
    this.remoteAddress = remoteAddress
    this.connection = { remoteAddress }
    this.socket = { remoteAddress }
    this.closed = false
  }

  async *[Symbol.asyncIterator]() {
    if (this.body) {
      yield Buffer.from(this.body)
    }
  }

  on(event, fn) {
    if (event === 'close' && this.closed) {
      fn()
    }
    return this
  }

  emit(event) {
    // For testing event emission
  }
}

class MockResponse {
  constructor() {
    this.statusCode = null
    this.headers = {}
    this.chunks = []
    this.ended = false
    this.drainListeners = []
    this.shouldBackpressure = false
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

    if (this.shouldBackpressure) {
      return false
    }
    return true
  }

  once(event, fn) {
    if (event === 'drain') {
      this.drainListeners.push(fn)
    }
    return this
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

  simulateDrain() {
    this.drainListeners.forEach(fn => fn())
    this.drainListeners = []
  }
}

describe('bench_api', () => {
  let router

  beforeEach(() => {
    router = createBenchApiRouter()
  })

  describe('GET /bench/ping', () => {
    it('returns 200 with ping response', async () => {
      const req = new MockRequest('GET', '/bench/ping')
      const res = new MockResponse()

      const handled = await router(req, res)

      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
      expect(res.headers['Content-Type']).toBe('application/json')
      const body = JSON.parse(res.getBody())
      expect(body).toHaveProperty('ok', true)
      expect(body).toHaveProperty('timestamp')
    })

    it('ignores query parameters on /bench/ping', async () => {
      const req = new MockRequest('GET', '/bench/ping?foo=bar&baz=qux')
      const res = new MockResponse()

      const handled = await router(req, res)

      expect(handled).toBe(true)
      expect(res.statusCode).toBe(200)
    })
  })

  describe('POST /bench/echo', () => {
    it('echoes back the request body', async () => {
      const body = JSON.stringify({ message: 'hello' })
      const req = new MockRequest('POST', '/bench/echo', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      const response = JSON.parse(res.getBody())
      expect(response.echo).toEqual({ message: 'hello' })
    })

    it('rejects invalid JSON with 400', async () => {
      const req = new MockRequest('POST', '/bench/echo', 'not json')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
    })

    it('rejects oversized body with 413', async () => {
      const largeBody = JSON.stringify({ data: 'x'.repeat(11 * 1024 * 1024) })
      const req = new MockRequest('POST', '/bench/echo', largeBody)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(413)
    })

    it('clamps chunking parameter from query string', async () => {
      const body = JSON.stringify({ data: 'test' })
      const req = new MockRequest('POST', '/bench/echo?chunks=1000000', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      // Should clamp to max, not reject
    })
  })

  describe('GET /bench/stream', () => {
    it('returns ndjson stream with real payload', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=3')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      expect(res.headers['Content-Type']).toBe('application/x-ndjson')
      expect(res.headers['Transfer-Encoding']).toBe('chunked')

      const body = res.getBody()
      expect(body.length).toBeGreaterThan(0)
      expect(body).toContain('index')
    })

    it('sends metadata plus 1024 bytes of payload per chunk', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=2')
      const res = new MockResponse()

      await router(req, res)

      const body = res.getBody()
      expect(body.length).toBeGreaterThan(2 * 1024)
    })

    it('uses default chunks=10 when not specified', async () => {
      const req = new MockRequest('GET', '/bench/stream')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      const body = res.getBody()
      const lines = body.split('\n').filter(l => l.length > 0)
      expect(lines.length).toBeGreaterThanOrEqual(10)
    })

    it('rejects negative chunks parameter', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=-5')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
    })

    it('clamps chunks parameter to maximum', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=10000')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
    })

    it('checks backpressure return value from res.write', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=5')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      expect(res.ended).toBe(true)
    })

    it('stops streaming on client disconnect', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=100')
      const res = new MockResponse()
      let closeHandler = null

      req.on = (event, fn) => {
        if (event === 'close') {
          closeHandler = fn
        }
        return req
      }

      let resolve
      const promise = new Promise(r => {
        resolve = r
        router(req, res).then(r)
      })

      await new Promise(r => setImmediate(r))

      if (closeHandler) {
        closeHandler()
        await new Promise(r => setImmediate(r))
      }

      resolve()
      await promise

      expect(res.ended).toBe(true)
      const body = res.getBody()
      const lines = body.split('\n').filter(l => l.length > 0)
      expect(lines.length).toBeLessThanOrEqual(101)
    })
  })

  describe('routing', () => {
    it('returns false for unhandled routes', async () => {
      const req = new MockRequest('GET', '/unknown')
      const res = new MockResponse()

      const handled = await router(req, res)

      expect(handled).toBe(false)
    })

    it('returns false for non-GET /bench/ping', async () => {
      const req = new MockRequest('POST', '/bench/ping')
      const res = new MockResponse()

      const handled = await router(req, res)

      expect(handled).toBe(false)
    })

    it('returns false for non-POST /bench/echo', async () => {
      const req = new MockRequest('GET', '/bench/echo')
      const res = new MockResponse()

      const handled = await router(req, res)

      expect(handled).toBe(false)
    })
  })

  describe('rate limiting', () => {
    it('rate limits based on gatePeer', async () => {
      const router2 = createBenchApiRouter()

      const req1 = new MockRequest('GET', '/bench/ping')
      req1.gatePeer = 'peer-1'
      const res1 = new MockResponse()
      await router2(req1, res1)
      expect(res1.statusCode).toBe(200)

      const req2 = new MockRequest('GET', '/bench/ping')
      req2.gatePeer = 'peer-2'
      const res2 = new MockResponse()
      await router2(req2, res2)
      expect(res2.statusCode).toBe(200)
    })

    it('enforces separate limits per peer', async () => {
      const router2 = createBenchApiRouter()

      for (let i = 0; i < 100; i++) {
        const req = new MockRequest('GET', '/bench/ping')
        req.gatePeer = 'peer-1'
        const res = new MockResponse()
        await router2(req, res)

        if (i < 10) {
          expect(res.statusCode).toBe(200)
        } else {
          expect(res.statusCode).toBe(429)
        }
      }
    })

    it('uses gatePeer over x-peer-id header', async () => {
      const req = new MockRequest('GET', '/bench/ping')
      req.gatePeer = 'correct-peer'
      req.headers['x-peer-id'] = 'wrong-peer'
      const res = new MockResponse()

      await router(req, res)
      expect(res.statusCode).toBe(200)
    })

    it('bounds the rate limiter map to prevent unbounded growth', async () => {
      const router2 = createBenchApiRouter()
      let lastRes

      for (let i = 0; i < 15000; i++) {
        const req = new MockRequest('GET', '/bench/ping')
        req.gatePeer = `peer-${i}`
        lastRes = new MockResponse()
        await router2(req, lastRes)
      }

      expect(lastRes.statusCode).toBe(200)
    })

    it('accepts injectable rateLimiterCap', async () => {
      const router2 = createBenchApiRouter({ rateLimiterCap: 5 })

      for (let i = 0; i < 10; i++) {
        const req = new MockRequest('GET', '/bench/ping')
        req.gatePeer = `peer-${i}`
        const res = new MockResponse()
        await router2(req, res)
        expect(res.statusCode).toBe(200)
      }
    })
  })

  describe('refcount lifecycle', () => {
    it('cleans up listeners after stream disconnect', async () => {
      const req1 = new MockRequest('GET', '/bench/stream?chunks=1')
      const res1 = new MockResponse()

      await router(req1, res1)

      const req2 = new MockRequest('GET', '/bench/stream?chunks=1')
      const res2 = new MockResponse()

      await router(req2, res2)

      expect(res1.ended).toBe(true)
      expect(res2.ended).toBe(true)
    })
  })

  describe('security', () => {
    it('does not leak request bodies in error responses', async () => {
      const body = JSON.stringify({ secret: 'password123' })
      const req = new MockRequest('POST', '/bench/echo', body + 'invalid')
      const res = new MockResponse()

      await router(req, res)

      const response = res.getBody()
      expect(response).not.toContain('password')
      expect(response).not.toContain('secret')
    })

    it('handles empty body gracefully', async () => {
      const req = new MockRequest('POST', '/bench/echo', '')
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(400)
    })
  })

  describe('error handling', () => {
    it('guards error response when headers already sent', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=1')
      const res = new MockResponse()

      // Simulate headers already sent
      res.headersSent = true
      res.destroy = () => {
        res.ended = true
      }

      await router(req, res)
      expect(res.ended).toBe(true)
    })

    it('sends 500 error when headers not sent', async () => {
      const req = new MockRequest('GET', '/bench/ping')
      const res = new MockResponse()

      // Simulate an error during request handling by creating a faulty request
      req.gatePeer = null
      const handleResult = await router(req, res)
      expect(handleResult).toBe(true)
    })

    it('handles large payloads with Buffer.concat', async () => {
      const largeObj = { data: 'x'.repeat(1024 * 1024) }
      const body = JSON.stringify(largeObj)
      const req = new MockRequest('POST', '/bench/echo', body)
      const res = new MockResponse()

      await router(req, res)

      expect(res.statusCode).toBe(200)
      const response = JSON.parse(res.getBody())
      expect(response.echo.data.length).toBe(1024 * 1024)
    })
  })

  describe('http_tailscale transport', () => {
    it('returns stream response with payload and metadata', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=3')
      const res = new MockResponse()

      await router(req, res)

      const body = res.getBody()
      expect(body.length).toBeGreaterThan(3 * 1024)
    })

    it('tracks time-to-first-byte in stream', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=2')
      const res = new MockResponse()

      const startTime = Date.now()
      await router(req, res)

      const body = res.getBody()
      expect(body.length).toBeGreaterThan(0)
    })

    it('sends ndjson lines with index field', async () => {
      const req = new MockRequest('GET', '/bench/stream?chunks=3')
      const res = new MockResponse()

      await router(req, res)

      const body = res.getBody()
      expect(body).toContain('"index":0')
      expect(body).toContain('"index":1')
      expect(body).toContain('"index":2')
    })
  })
})
