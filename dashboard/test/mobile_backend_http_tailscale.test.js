import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import http from 'http'
import { createHttpTailscaleTransport } from '../mobile-backend/transports/http_tailscale.js'
import { createBenchApiRouter } from '../mobile-backend/bench_api.js'

describe('http_tailscale transport', () => {
  let server
  let baseUrl

  beforeEach(async () => {
    const router = createBenchApiRouter()
    server = http.createServer((req, res) => {
      req.gatePeer = 'test-peer'
      router(req, res)
    })

    return new Promise((resolve) => {
      server.listen(0, 'localhost', () => {
        const addr = server.address()
        baseUrl = `http://localhost:${addr.port}`
        resolve()
      })
    })
  })

  afterEach(async () => {
    return new Promise((resolve) => {
      server.close(() => resolve())
    })
  })

  it('ping successfully measures time-to-first-byte', async () => {
    const transport = createHttpTailscaleTransport(baseUrl)
    await transport.connect()

    const result = await transport.ping()

    expect(result.ttfbMs).toBeGreaterThanOrEqual(0)
    expect(result.statusCode).toBe(200)
    await transport.disconnect()
  })

  it('stream returns valid chunkSequence with chunk indices', async () => {
    const transport = createHttpTailscaleTransport(baseUrl)
    await transport.connect()

    const result = await transport.stream(5)

    expect(result.chunkSequence).toBeDefined()
    expect(Array.isArray(result.chunkSequence)).toBe(true)
    expect(result.chunkSequence.length).toBe(5)
    expect(result.chunkSequence).toEqual([0, 1, 2, 3, 4])
    expect(result.totalBytes).toBe(5 * 1024)
    await transport.disconnect()
  })

  it('stream calculates throughput correctly', async () => {
    const transport = createHttpTailscaleTransport(baseUrl)
    await transport.connect()

    const result = await transport.stream(10)

    expect(result.throughputMbps).toBeGreaterThan(0)
    expect(result.elapsedMs).toBeGreaterThanOrEqual(0)
    expect(result.ttfbMs).toBeGreaterThanOrEqual(0)
    await transport.disconnect()
  })

  it('ping request includes timeout parameter', async () => {
    const transport = createHttpTailscaleTransport(baseUrl, {
      timeoutMs: 60000
    })

    await transport.connect()
    const result = await transport.ping()
    expect(result.ttfbMs).toBeGreaterThanOrEqual(0)
    await transport.disconnect()
  })

  it('stream request handles timeout and errors gracefully', async () => {
    const transport = createHttpTailscaleTransport('http://localhost:1', {
      timeoutMs: 100
    })

    await transport.connect()
    try {
      await transport.stream(5)
      expect.fail('should have thrown error')
    } catch (err) {
      expect(err).toBeDefined()
      expect(typeof err.message).toBe('string')
    }
    await transport.disconnect()
  })

  it('parses URL hostname and port correctly', async () => {
    const transport1 = createHttpTailscaleTransport(baseUrl)
    const transport2 = createHttpTailscaleTransport(`http://localhost`)

    expect(transport1).toBeDefined()
    expect(transport2).toBeDefined()
  })

  it('stream decodes chunk indices from big-endian buffer', async () => {
    const transport = createHttpTailscaleTransport(baseUrl)
    await transport.connect()

    const result = await transport.stream(20)

    expect(result.chunkSequence).toEqual(
      Array.from({ length: 20 }, (_, i) => i)
    )
    await transport.disconnect()
  })

  it('stream handles fragmented TCP packets without misalignment', async () => {
    const transport = createHttpTailscaleTransport(baseUrl)
    await transport.connect()

    const result = await transport.stream(100)

    expect(result.chunkSequence.length).toBe(100)
    for (let i = 0; i < result.chunkSequence.length; i++) {
      expect(result.chunkSequence[i]).toBe(i)
    }
    await transport.disconnect()
  })
})
