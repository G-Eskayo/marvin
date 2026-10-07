import { describe, it, expect, vi, afterEach } from 'vitest'
import { createLiveApiRouter } from '../mobile-backend/live_api.js'

let server

afterEach(() => {
  server?.close()
  server = null
})

function listen(srv) {
  return new Promise((resolve) => {
    srv.listen(0, '127.0.0.1', () => resolve(srv.address().port))
  })
}

describe('createLiveApiRouter', () => {
  it('returns false for non-/live routes', async () => {
    const mockChannel = { connect: vi.fn(), disconnect: vi.fn() }
    const router = createLiveApiRouter(mockChannel)

    class MockRequest {
      constructor(method, url) {
        this.method = method
        this.url = url
        this.headers = { host: 'localhost' }
      }
    }

    class MockResponse {
      writeHead() {}
      end() {}
    }

    const req = new MockRequest('GET', '/other')
    const res = new MockResponse()

    const result = await router(req, res)
    expect(result).toBe(false)
    expect(mockChannel.connect).not.toHaveBeenCalled()
  })

  it('opens a streaming /live endpoint and broadcasts trigger events', async () => {
    const mockChannel = {
      connect: vi.fn((cb) => {
        // Immediately emit a test event
        setTimeout(() => cb({ topic: 'activity', source: 'test' }), 10)
      }),
      disconnect: vi.fn()
    }

    const router = createLiveApiRouter(mockChannel)

    // Start a real HTTP server
    const { createServer } = await import('http')
    server = createServer(async (req, res) => {
      const handled = await router(req, res)
      if (!handled) res.writeHead(404).end()
    })

    const port = await listen(server)

    // Fetch with AbortController to simulate client disconnect
    const controller = new AbortController()
    const fetchPromise = fetch(`http://127.0.0.1:${port}/live`, {
      signal: controller.signal
    })

    // Give the server time to start streaming
    await new Promise((r) => setTimeout(r, 50))

    // Abort the fetch to close the connection
    controller.abort()

    try {
      const response = await fetchPromise
    } catch (err) {
      // Expected: AbortError
    }

    // Give time for the close event to propagate
    await new Promise((r) => setTimeout(r, 100))

    // Verify connect was called
    expect(mockChannel.connect).toHaveBeenCalled()
  })

  it('streams trigger events as NDJSON', async () => {
    let connectedCallback

    const mockChannel = {
      connect: vi.fn((cb) => {
        connectedCallback = cb
      }),
      disconnect: vi.fn()
    }

    const router = createLiveApiRouter(mockChannel)

    // Start a real HTTP server
    const { createServer } = await import('http')
    server = createServer(async (req, res) => {
      const handled = await router(req, res)
      if (!handled) res.writeHead(404).end()
    })

    const port = await listen(server)

    // Start fetch in background
    let responseBody = ''
    const controller = new AbortController()

    const fetchPromise = (async () => {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/live`, {
          signal: controller.signal
        })
        const reader = response.body.getReader()
        const decoder = new TextDecoder()

        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            responseBody += decoder.decode(value)
          }
        } catch (e) {
          // Expected on abort
        }
      } catch (e) {
        // Expected on abort
      }
    })()

    // Give server time to connect
    await new Promise((r) => setTimeout(r, 50))

    // Emit test events through the connected callback
    if (connectedCallback) {
      connectedCallback({ topic: 'activity', source: 'file:state.json' })
      connectedCallback({ topic: 'agents', source: 'ping' })
    }

    // Give time for events to be written
    await new Promise((r) => setTimeout(r, 50))

    // Abort to close the connection
    controller.abort()
    await fetchPromise

    // Verify we got NDJSON lines
    const lines = responseBody.trim().split('\n').filter((l) => l.length > 0)
    expect(lines.length).toBeGreaterThanOrEqual(1)

    if (lines.length > 0) {
      const firstEvent = JSON.parse(lines[0])
      expect(firstEvent).toHaveProperty('topic')
      expect(firstEvent).toHaveProperty('source')
    }
  })

  it('calls disconnect when the client closes the connection', async () => {
    let savedCb
    const mockChannel = {
      connect: vi.fn((cb) => {
        savedCb = cb
      }),
      disconnect: vi.fn()
    }

    const router = createLiveApiRouter(mockChannel)

    // Create a mock request with a close event
    const EventEmitter = (await import('events')).EventEmitter
    const mockReq = new EventEmitter()
    mockReq.method = 'GET'
    mockReq.url = '/live'
    mockReq.headers = { host: 'localhost' }

    class MockResponse {
      constructor() {
        this.chunks = []
      }

      writeHead() {
        return this
      }

      write(chunk) {
        this.chunks.push(chunk)
      }

      end() {}
    }

    const mockRes = new MockResponse()

    // Call the router
    const handled = await router(mockReq, mockRes)
    expect(handled).toBe(true)
    expect(mockChannel.connect).toHaveBeenCalledTimes(1)

    // Simulate the client closing the connection
    mockReq.emit('close')

    // Verify disconnect was called
    expect(mockChannel.disconnect).toHaveBeenCalledTimes(1)
  })

  it('returns true to indicate the route was handled', async () => {
    const mockChannel = {
      connect: vi.fn(),
      disconnect: vi.fn()
    }

    const router = createLiveApiRouter(mockChannel)

    class MockRequest {
      constructor(method, url) {
        this.method = method
        this.url = url
        this.headers = { host: 'localhost' }
        this.on = vi.fn()
        this.removeListener = vi.fn()
      }
    }

    class MockResponse {
      writeHead() {
        return this
      }

      end() {}
    }

    const req = new MockRequest('GET', '/live')
    const res = new MockResponse()

    const result = await router(req, res)
    expect(result).toBe(true)
  })
})
