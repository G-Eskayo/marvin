import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createLiveChannel } from '../mobile-backend/live_channel.js'

describe('live channel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns false for non-/live paths', async () => {
    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn(),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const mockReq = { method: 'GET', url: '/other', headers: { host: 'localhost' } }
    const mockRes = {}

    const result = await router(mockReq, mockRes)
    expect(result).toBe(false)
  })

  it('returns false for POST on /live (not GET)', async () => {
    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn(),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const mockReq = { method: 'POST', url: '/live', headers: { host: 'localhost' } }
    const mockRes = {}

    const result = await router(mockReq, mockRes)
    expect(result).toBe(false)
  })

  it('handles GET /live by setting SSE headers and returning true', async () => {
    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn(),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const headers = {}
    const written = []

    const mockReq = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes = {
      writeHead: vi.fn((status, headersObj) => {
        Object.assign(headers, headersObj)
        return mockRes
      }),
      write: vi.fn((data) => {
        written.push(data)
        return mockRes
      }),
      destroy: vi.fn()
    }

    const result = await router(mockReq, mockRes)

    expect(result).toBe(true)
    expect(mockRes.writeHead).toHaveBeenCalledWith(200, expect.objectContaining({
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    }))
    expect(written[0]).toContain('event: connected')
    expect(written[0]).toContain('"ok":true')
  })

  it('starts hub on first client connection', async () => {
    let triggerCallback

    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn((cb) => {
        triggerCallback = cb
      }),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const mockReq = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes = {
      writeHead: vi.fn(() => mockRes),
      write: vi.fn(() => mockRes),
      destroy: vi.fn()
    }

    await router(mockReq, mockRes)

    // Hub should be started and watchFiles called
    expect(mockHub.watchFiles).toHaveBeenCalledTimes(2)
    expect(triggerCallback).toBeDefined()
  })

  it('does not start hub before any client connects', async () => {
    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn(),
      close: vi.fn()
    }

    createLiveChannel({ createHub: () => mockHub })

    // Hub should not be started yet
    expect(mockHub.watchFiles).not.toHaveBeenCalled()
  })

  it('broadcasts activity triggers to connected clients', async () => {
    let triggerCallback

    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn((cb) => {
        triggerCallback = cb
      }),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const written1 = []
    const mockReq1 = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes1 = {
      writeHead: vi.fn(() => mockRes1),
      write: vi.fn((data) => {
        written1.push(data)
        return mockRes1
      }),
      destroy: vi.fn()
    }

    await router(mockReq1, mockRes1)

    // Simulate a trigger
    triggerCallback({ topic: 'activity', source: 'file:dispatch.json' })

    expect(written1.length).toBeGreaterThan(1) // connected frame + trigger frame
    expect(written1[written1.length - 1]).toContain('event: trigger')
    expect(written1[written1.length - 1]).toContain('dispatch.json')
  })

  it('broadcasts docs triggers to connected clients', async () => {
    let triggerCallback

    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn((cb) => {
        triggerCallback = cb
      }),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const written = []
    const mockReq = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes = {
      writeHead: vi.fn(() => mockRes),
      write: vi.fn((data) => {
        written.push(data)
        return mockRes
      }),
      destroy: vi.fn()
    }

    await router(mockReq, mockRes)

    // Simulate a trigger
    triggerCallback({ topic: 'docs', source: 'file:master.md' })

    const lastWrite = written[written.length - 1]
    expect(lastWrite).toContain('event: trigger')
    expect(lastWrite).toContain('"topic":"docs"')
  })

  it('does not broadcast non-activity/docs triggers', async () => {
    let triggerCallback

    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn((cb) => {
        triggerCallback = cb
      }),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const written = []
    const mockReq = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes = {
      writeHead: vi.fn(() => mockRes),
      write: vi.fn((data) => {
        written.push(data)
        return mockRes
      }),
      destroy: vi.fn()
    }

    await router(mockReq, mockRes)

    const initialWriteCount = written.length

    // Trigger agents (should NOT relay)
    triggerCallback({ topic: 'agents', source: 'file:run.json' })

    // Trigger mr (should NOT relay)
    triggerCallback({ topic: 'mr', source: 'ping' })

    expect(written.length).toBe(initialWriteCount) // no new writes
  })

  it('closes hub when last client disconnects', async () => {
    let triggerCallback
    let closeHandler

    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn((cb) => {
        triggerCallback = cb
      }),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const mockReq = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn((event, handler) => {
        if (event === 'close') {
          closeHandler = handler
        }
      })
    }
    const mockRes = {
      writeHead: vi.fn(() => mockRes),
      write: vi.fn(() => mockRes),
      destroy: vi.fn()
    }

    await router(mockReq, mockRes)

    expect(mockHub.close).not.toHaveBeenCalled()

    // Simulate client disconnect
    closeHandler()
    vi.advanceTimersByTime(50)

    expect(mockHub.close).toHaveBeenCalledTimes(1)
  })

  it('supports multiple simultaneous connections', async () => {
    let triggerCallback

    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn((cb) => {
        triggerCallback = cb
      }),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    // First connection
    const written1 = []
    const mockReq1 = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes1 = {
      writeHead: vi.fn(() => mockRes1),
      write: vi.fn((data) => {
        written1.push(data)
        return mockRes1
      }),
      destroy: vi.fn()
    }

    await router(mockReq1, mockRes1)

    // Second connection
    const written2 = []
    const mockReq2 = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes2 = {
      writeHead: vi.fn(() => mockRes2),
      write: vi.fn((data) => {
        written2.push(data)
        return mockRes2
      }),
      destroy: vi.fn()
    }

    await router(mockReq2, mockRes2)

    // Trigger an event
    triggerCallback({ topic: 'activity', source: 'file:test.json' })

    // Both clients should receive the event
    const triggerEvents1 = written1.filter(w => w.includes('event: trigger'))
    const triggerEvents2 = written2.filter(w => w.includes('event: trigger'))

    expect(triggerEvents1.length).toBeGreaterThan(0)
    expect(triggerEvents2.length).toBeGreaterThan(0)
    expect(triggerEvents1[0]).toEqual(triggerEvents2[0])
  })

  it('sends heartbeat comments periodically', async () => {
    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn(),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    const written = []
    const mockReq = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn()
    }
    const mockRes = {
      writeHead: vi.fn(() => mockRes),
      write: vi.fn((data) => {
        written.push(data)
        return mockRes
      }),
      destroy: vi.fn()
    }

    await router(mockReq, mockRes)

    const initialWriteCount = written.length

    // Advance past heartbeat interval (30s)
    vi.advanceTimersByTime(30000)
    vi.advanceTimersByTime(100)

    // Should have written heartbeat comments
    expect(written.length).toBeGreaterThan(initialWriteCount)
    const heartbeatWrites = written.filter(w => w.includes(': heartbeat'))
    expect(heartbeatWrites.length).toBeGreaterThan(0)
  })

  it('restarts watching on reconnect after full disconnect', async () => {
    let triggerCallback
    let closeHandler

    const mockHub = {
      watchFiles: vi.fn(),
      onTrigger: vi.fn((cb) => {
        triggerCallback = cb
      }),
      close: vi.fn()
    }

    const router = createLiveChannel({ createHub: () => mockHub })

    // First connection
    const mockReq1 = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn((event, handler) => {
        if (event === 'close') {
          closeHandler = handler
        }
      })
    }
    const mockRes1 = {
      writeHead: vi.fn(() => mockRes1),
      write: vi.fn(() => mockRes1),
      destroy: vi.fn()
    }

    await router(mockReq1, mockRes1)
    expect(mockHub.watchFiles).toHaveBeenCalledTimes(2)

    // Disconnect
    closeHandler()
    vi.advanceTimersByTime(50)
    expect(mockHub.close).toHaveBeenCalledTimes(1)

    // Reconnect
    let closeHandler2
    const mockReq2 = {
      method: 'GET',
      url: '/live',
      headers: { host: 'localhost' },
      on: vi.fn((event, handler) => {
        if (event === 'close') {
          closeHandler2 = handler
        }
      })
    }
    const mockRes2 = {
      writeHead: vi.fn(() => mockRes2),
      write: vi.fn(() => mockRes2),
      destroy: vi.fn()
    }

    await router(mockReq2, mockRes2)

    // watchFiles should be called again (2 calls per hub creation)
    expect(mockHub.watchFiles.mock.calls.length).toBe(4) // 2 + 2
  })
})
