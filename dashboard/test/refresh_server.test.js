import { describe, it, expect, vi, afterEach } from 'vitest'
import { createServer } from 'http'
import { createRefreshServer, parseRefreshPort, startRefreshServer } from '../electron/main/refresh_server.js'

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

describe('createRefreshServer', () => {
  it('calls onRefresh for a POST /refresh and responds ok', async () => {
    const onRefresh = vi.fn()
    server = createRefreshServer(onRefresh)
    const port = await listen(server)

    const response = await fetch(`http://127.0.0.1:${port}/refresh`, { method: 'POST' })

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ ok: true })
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('passes a JSON body (topics, source) through to onRefresh, tolerating junk', async () => {
    const onRefresh = vi.fn()
    server = createRefreshServer(onRefresh)
    const port = await listen(server)
    const url = `http://127.0.0.1:${port}/refresh`

    await fetch(url, { method: 'POST', body: JSON.stringify({ topics: ['activity'], source: 'github:o/r' }) })
    await fetch(url, { method: 'POST', body: '{not json' })

    expect(onRefresh).toHaveBeenNthCalledWith(1, { topics: ['activity'], source: 'github:o/r' })
    expect(onRefresh).toHaveBeenNthCalledWith(2, {})
  })

  it('responds 404 and does not call onRefresh for any other route', async () => {
    const onRefresh = vi.fn()
    server = createRefreshServer(onRefresh)
    const port = await listen(server)

    const response = await fetch(`http://127.0.0.1:${port}/other`, { method: 'POST' })

    expect(response.status).toBe(404)
    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('responds 404 and does not call onRefresh for a GET on /refresh', async () => {
    const onRefresh = vi.fn()
    server = createRefreshServer(onRefresh)
    const port = await listen(server)

    const response = await fetch(`http://127.0.0.1:${port}/refresh`, { method: 'GET' })

    expect(response.status).toBe(404)
    expect(onRefresh).not.toHaveBeenCalled()
  })
})

describe('parseRefreshPort', () => {
  it('honours 0 (ephemeral) instead of turning it into the default', () => {
    expect(parseRefreshPort('0')).toBe(0)
  })

  it('uses a valid port as given', () => {
    expect(parseRefreshPort('8123')).toBe(8123)
    expect(parseRefreshPort(' 65535 ')).toBe(65535)
  })

  it('falls back to 7879 when unset or empty', () => {
    expect(parseRefreshPort(undefined)).toBe(7879)
    expect(parseRefreshPort('')).toBe(7879)
    expect(parseRefreshPort('   ')).toBe(7879)
  })

  it('falls back to 7879 for junk, negatives, fractions and out-of-range values', () => {
    for (const bad of ['abc', '-1', '1.5', '65536', '99999', 'NaN', 'Infinity', '0x1f', '1e3', '12abc']) {
      expect(parseRefreshPort(bad), bad).toBe(7879)
    }
  })
})

describe('startRefreshServer', () => {
  const servers = []
  afterEach(async () => {
    await Promise.all(servers.splice(0).map((s) => new Promise((r) => (s.listening ? s.close(r) : r()))))
  })

  function listening(srv) {
    return new Promise((resolve) => (srv.listening ? resolve() : srv.once('listening', resolve)))
  }

  async function holdAPort() {
    const holder = createServer(() => {})
    servers.push(holder)
    await new Promise((r) => holder.listen(0, '127.0.0.1', r))
    return holder.address().port
  }

  it('listens on an ephemeral port when given 0 and still serves /refresh', async () => {
    const onRefresh = vi.fn()
    const srv = startRefreshServer(onRefresh, { port: 0, log: vi.fn() })
    servers.push(srv)
    await listening(srv)
    const { port } = srv.address()
    expect(port).toBeGreaterThan(0)
    const response = await fetch(`http://127.0.0.1:${port}/refresh`, { method: 'POST' })
    expect(response.status).toBe(200)
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('does not throw when the port is already taken; logs one clear line instead', async () => {
    const takenPort = await holdAPort()
    const log = vi.fn()
    const uncaught = vi.fn()
    process.on('uncaughtException', uncaught)
    try {
      const srv = startRefreshServer(vi.fn(), { port: takenPort, log })
      servers.push(srv)
      await new Promise((r) => setTimeout(r, 100))
      expect(srv.listening).toBe(false)
    } finally {
      process.off('uncaughtException', uncaught)
    }
    expect(uncaught).not.toHaveBeenCalled()
    expect(log).toHaveBeenCalledTimes(1)
    expect(log.mock.calls[0][0]).toBe(
      `refresh port ${takenPort} in use — another dashboard is running; live refresh pings disabled for this instance`
    )
  })

  it('logs (not throws) any other listen error, e.g. an unbindable host', async () => {
    const log = vi.fn()
    const srv = startRefreshServer(vi.fn(), { port: 0, host: '203.0.113.1', log })
    servers.push(srv)
    await new Promise((r) => setTimeout(r, 200))
    expect(srv.listening).toBe(false)
    expect(log).toHaveBeenCalledTimes(1)
    expect(log.mock.calls[0][0]).toMatch(/refresh server failed to start/)
  })

  it('keeps handling errors raised after a successful listen', async () => {
    const log = vi.fn()
    const srv = startRefreshServer(vi.fn(), { port: 0, log })
    servers.push(srv)
    await listening(srv)
    expect(() => srv.emit('error', Object.assign(new Error('boom'), { code: 'ECONNRESET' }))).not.toThrow()
    expect(log).toHaveBeenCalledTimes(1)
  })

  it('a throwing logger still never crashes the process', async () => {
    const takenPort = await holdAPort()
    const srv = startRefreshServer(vi.fn(), {
      port: takenPort,
      log: () => { throw new Error('stdout closed') }
    })
    servers.push(srv)
    expect(() => srv.emit('error', Object.assign(new Error('x'), { code: 'EADDRINUSE' }))).not.toThrow()
  })

  it('defaults the log to console.warn', async () => {
    const takenPort = await holdAPort()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const srv = startRefreshServer(vi.fn(), { port: takenPort })
      servers.push(srv)
      await new Promise((r) => setTimeout(r, 100))
      expect(warn).toHaveBeenCalledTimes(1)
    } finally {
      warn.mockRestore()
    }
  })
})
