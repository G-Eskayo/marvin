import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { probeMergeServerHealth, getMergeServerHealth, clearMergeServerHealthCache } from '../electron/main/merge_server_health.js'

describe('probeMergeServerHealth', () => {
  let fetchImpl

  beforeEach(() => {
    fetchImpl = vi.fn()
  })

  it('returns down: true when fetch rejects with TimeoutError (AbortSignal.timeout)', async () => {
    fetchImpl.mockRejectedValue(new DOMException('timeout', 'TimeoutError'))
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1000 })
    expect(result.down).toBe(true)
    expect(result.error).toBeDefined()
  })

  it('returns down: true on ECONNREFUSED', async () => {
    const cause = new Error('Connection refused')
    cause.code = 'ECONNREFUSED'
    const err = new TypeError('fetch failed')
    err.cause = cause
    fetchImpl.mockRejectedValue(err)
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1000 })
    expect(result.down).toBe(true)
  })

  it('returns down: true on ENOTFOUND', async () => {
    const cause = new Error('getaddrinfo ENOTFOUND')
    cause.code = 'ENOTFOUND'
    const err = new TypeError('fetch failed')
    err.cause = cause
    fetchImpl.mockRejectedValue(err)
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1000 })
    expect(result.down).toBe(true)
  })

  it('returns down: true on EHOSTUNREACH', async () => {
    const cause = new Error('Host unreachable')
    cause.code = 'EHOSTUNREACH'
    const err = new TypeError('fetch failed')
    err.cause = cause
    fetchImpl.mockRejectedValue(err)
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1000 })
    expect(result.down).toBe(true)
  })

  it('returns down: true when response is not ok (e.g., 500)', async () => {
    const response = { ok: false, status: 500, text: async () => 'Internal error' }
    fetchImpl.mockResolvedValue(response)
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1000 })
    expect(result.down).toBe(true)
  })

  it('returns down: false on a 200 response, ignoring body', async () => {
    const response = { ok: true, status: 200, text: async () => 'garbage data {{{' }
    fetchImpl.mockResolvedValue(response)
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1000 })
    expect(result.down).toBe(false)
  })

  it('never throws, always returns a result object', async () => {
    fetchImpl.mockRejectedValue(new Error('unexpected error'))
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1000 })
    expect(result).toBeDefined()
    expect(typeof result.down).toBe('boolean')
  })

  it('uses AbortSignal.timeout for the timeout', async () => {
    const timeoutMsSpy = vi.spyOn(AbortSignal, 'timeout')
    try {
      fetchImpl.mockResolvedValue({ ok: true, status: 200 })
      await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 1500 })
      expect(timeoutMsSpy).toHaveBeenCalledWith(1500)
    } finally {
      timeoutMsSpy.mockRestore()
    }
  })

  it('handles TimeoutError from AbortSignal.timeout', async () => {
    fetchImpl.mockRejectedValue(new DOMException('The operation timed out', 'TimeoutError'))
    const result = await probeMergeServerHealth('http://localhost:7878/health', { fetchImpl, timeoutMs: 100 })
    expect(result.down).toBe(true)
    expect(result.error).toContain('timed out')
  })
})

describe('getMergeServerHealth', () => {
  let fetchImpl
  let now

  beforeEach(() => {
    fetchImpl = vi.fn()
    now = Date.now()
    clearMergeServerHealthCache()
  })

  afterEach(() => {
    clearMergeServerHealthCache()
  })

  it('returns a cached value within the TTL window', async () => {
    fetchImpl.mockResolvedValue({ ok: true, status: 200 })
    const first = await getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now,
      fetchImpl,
      ttlMs: 30_000
    })
    expect(first.down).toBe(false)
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    fetchImpl.mockRejectedValue(new Error('should not be called'))
    const second = await getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now: now + 10_000,
      fetchImpl,
      ttlMs: 30_000
    })
    expect(second.down).toBe(false)
    expect(fetchImpl).toHaveBeenCalledTimes(1) // No new call
  })

  it('expires the cache after TTL', async () => {
    fetchImpl.mockResolvedValue({ ok: true, status: 200 })
    await getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now,
      fetchImpl,
      ttlMs: 30_000
    })
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    fetchImpl.mockRejectedValue(new Error('connect ECONNREFUSED'))
    const stale = await getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now: now + 35_000,
      fetchImpl,
      ttlMs: 30_000
    })
    expect(stale.down).toBe(true) // Reflects new failure, not cached
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })

  it('shares a single in-flight promise for concurrent calls', async () => {
    let resolveProbe
    fetchImpl.mockImplementation(() => new Promise((resolve) => {
      resolveProbe = resolve
    }))

    const p1 = getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now,
      fetchImpl,
      ttlMs: 30_000
    })
    const p2 = getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now,
      fetchImpl,
      ttlMs: 30_000
    })

    expect(fetchImpl).toHaveBeenCalledTimes(1) // Only one request started
    resolveProbe({ ok: true, status: 200 })
    const [r1, r2] = await Promise.all([p1, p2])
    expect(r1).toEqual(r2)
  })

  it('defaults to "assume up" when probeMergeServerHealth throws', async () => {
    // Test getMergeServerHealth's catch block by forcing probeMergeServerHealth to throw
    // This happens if fetchImpl is not a function (programming error scenario)
    const result = await getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now,
      fetchImpl: 'not a function',  // This will cause probeMergeServerHealth to throw
      ttlMs: 30_000
    })
    // getMergeServerHealth's catch block should catch this and default to down: false
    expect(result.down).toBe(false)
    expect(result.error).toBeDefined()
  })

  it('clearMergeServerHealthCache forces a new probe', async () => {
    fetchImpl.mockResolvedValue({ ok: true, status: 200 })
    await getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now,
      fetchImpl,
      ttlMs: 30_000
    })
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    clearMergeServerHealthCache()

    await getMergeServerHealth({
      url: 'http://localhost:7878/health',
      now,
      fetchImpl,
      ttlMs: 30_000
    })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
  })
})
