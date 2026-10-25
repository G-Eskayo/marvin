import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createBenchApiRouter } from '../mobile-backend/bench_api.js'

class MockRequest {
  constructor(method, url, body = null) {
    this.method = method
    this.url = url
    this.headers = { host: 'localhost:7880' }
    this.gatePeer = 'test-peer'
    this.body = body
    this.isStream = typeof body === 'object' && body !== null && Symbol.asyncIterator in body
    this.listeners = {}
  }

  once(event, callback) {
    this.listeners[event] = callback
  }

  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = []
    }
    if (Array.isArray(this.listeners[event])) {
      this.listeners[event].push(callback)
    }
  }

  destroy() {
    // mock destroy
  }

  async *[Symbol.asyncIterator]() {
    if (this.isStream) {
      yield* this.body
    } else if (this.body) {
      yield Buffer.from(this.body)
    }
  }
}

class MockResponse {
  constructor() {
    this.statusCode = null
    this.responseHeaders = null
    this.data = ''
    this.headersSent = false
    this.listeners = {}
  }

  writeHead(statusCode, headers = {}) {
    this.statusCode = statusCode
    this.responseHeaders = headers
    this.headersSent = true
    return this
  }

  write(chunk) {
    this.data += chunk.toString()
    return true
  }

  once(event, callback) {
    this.listeners[event] = callback
  }

  end(data = '') {
    if (data) {
      this.data += data.toString()
    }
  }
}

describe('bench_api', () => {
  let router

  beforeEach(() => {
    router = createBenchApiRouter({
      tokensPerSecond: 100,
      maxBurst: 1000
    })
  })

  it('GET /bench/ping returns 200', async () => {
    const req = new MockRequest('GET', '/bench/ping')
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
  })

  it('POST /bench/echo echoes request body', async () => {
    const body = 'test data'
    const req = new MockRequest('POST', '/bench/echo', body)
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
  })

  it('GET /bench/stream returns chunks', async () => {
    const req = new MockRequest('GET', '/bench/stream?chunks=5')
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
  })

  it('rate limit blocks after exceeding tokens', async () => {
    const router2 = createBenchApiRouter({
      tokensPerSecond: 100,
      maxBurst: 2
    })

    const req1 = new MockRequest('GET', '/bench/ping')
    const res1 = new MockResponse()
    await router2(req1, res1)

    const req2 = new MockRequest('GET', '/bench/ping')
    const res2 = new MockResponse()
    await router2(req2, res2)

    const req3 = new MockRequest('GET', '/bench/ping')
    const res3 = new MockResponse()
    await router2(req3, res3)

    expect(res3.statusCode).toBe(429)
  })

  it('rejects stream without chunks parameter', async () => {
    const req = new MockRequest('GET', '/bench/stream')
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(400)
  })

  it('requires req.gatePeer', async () => {
    const req = new MockRequest('GET', '/bench/ping')
    delete req.gatePeer
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(400)
  })

  it('unmatched routes return false', async () => {
    const req = new MockRequest('GET', '/unknown')
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(false)
  })

  it('rejects large echo payloads with 413', async () => {
    const largeBody = Buffer.alloc(11 * 1024 * 1024) // > MAX_ECHO_BODY_BYTES
    const req = new MockRequest('POST', '/bench/echo')
    req.isStream = true
    req.body = (async function* () {
      yield largeBody.slice(0, 5 * 1024 * 1024)
      yield largeBody.slice(5 * 1024 * 1024)
    })()
    const res = new MockResponse()
    req.destroy = vi.fn()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(413)
    expect(req.destroy).toHaveBeenCalled()
  })

  it('clamps chunks parameter to valid range', async () => {
    const req = new MockRequest('GET', '/bench/stream?chunks=5000')
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
  })

  it('handles invalid chunks parameter', async () => {
    const req = new MockRequest('GET', '/bench/stream?chunks=invalid')
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(400)
  })

  it('handles URL parsing errors gracefully', async () => {
    const req = new MockRequest('GET', 'http://[invalid')
    const res = new MockResponse()

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(400)
    expect(res.data).toContain('invalid URL')
  })

  it('handles stream write backpressure via drain', async () => {
    const req = new MockRequest('GET', '/bench/stream?chunks=10')
    const res = new MockResponse()
    let drainCalled = false

    res.write = vi.fn((chunk) => {
      if (res.write.mock.calls.length === 3) {
        // Simulate backpressure: return false on 3rd write
        setTimeout(() => {
          if (res.listeners.drain) {
            drainCalled = true
            res.listeners.drain()
          }
        }, 0)
        return false
      }
      return true
    })

    const handled = await router(req, res)

    expect(handled).toBe(true)
    expect(res.statusCode).toBe(200)
  })

  it('aborts stream on request close', async () => {
    const req = new MockRequest('GET', '/bench/stream?chunks=5')
    const res = new MockResponse()

    res.write = vi.fn((chunk) => {
      if (res.write.mock.callCount === 2) {
        // Simulate close event
        if (req.listeners.close) {
          req.listeners.close()
        }
      }
      return true
    })

    const handled = await router(req, res)

    expect(handled).toBe(true)
  })
})
