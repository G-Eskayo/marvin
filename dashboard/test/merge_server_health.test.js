import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createMergeServerHealth } from '../electron/main/merge_server_health.js'

describe('createMergeServerHealth', () => {
  let probe, health

  beforeEach(() => {
    probe = vi.fn()
    health = createMergeServerHealth({ probe, ttlMs: 50, now: () => Date.now() })
  })

  it('test 1: check() calls probe and caches the result', async () => {
    probe.mockResolvedValue(true)
    const result1 = await health.check()
    expect(result1).toBe(true)
    expect(probe).toHaveBeenCalledTimes(1)

    const result2 = await health.check()
    expect(result2).toBe(true)
    expect(probe).toHaveBeenCalledTimes(1) // cached
  })

  it('test 2: check() respects TTL', async () => {
    let currentTime = 1000
    const now = () => currentTime
    probe.mockResolvedValue(true)
    const health2 = createMergeServerHealth({
      probe,
      ttlMs: 100,
      now
    })
    await health2.check()
    expect(probe).toHaveBeenCalledTimes(1)

    // Time hasn't passed TTL yet, should use cache
    currentTime = 1050
    const result2 = await health2.check()
    expect(result2).toBe(true)
    expect(probe).toHaveBeenCalledTimes(1) // still cached

    // Time passed TTL, should probe again
    currentTime = 1150
    await health2.check()
    expect(probe).toHaveBeenCalledTimes(2) // TTL expired, called again
  })

  it('test 3: check() handles probe errors by returning false', async () => {
    probe.mockRejectedValue(new Error('connection failed'))
    const result = await health.check()
    expect(result).toBe(false)
  })

  it('test 4: peek() returns last cached result without calling probe', async () => {
    probe.mockResolvedValue(true)
    await health.check()
    probe.mockClear()

    const peeked = health.peek()
    expect(peeked).toBe(true)
    expect(probe).not.toHaveBeenCalled()
  })

  it('test 5: peek() returns null if nothing cached yet', () => {
    const result = health.peek()
    expect(result).toBe(null)
  })

  it('test 6: lastCheckedAt() returns timestamp of last check', async () => {
    const now = 12345
    probe.mockResolvedValue(true)
    const health2 = createMergeServerHealth({
      probe,
      ttlMs: 50,
      now: () => now
    })
    const before = health2.lastCheckedAt()
    expect(before).toBe(null)

    await health2.check()
    const after = health2.lastCheckedAt()
    expect(after).toBe(now)
  })

  it('test 7-probe-accepts-any-http-response: any successful probe result (including false from probe) is cached', async () => {
    // This test ensures that when the probe function itself returns a boolean value
    // (not throws), that value is cached and returned, even if false
    probe.mockResolvedValue(false)
    const result = await health.check()
    expect(result).toBe(false)
    expect(probe).toHaveBeenCalledTimes(1)
  })

  it('test 8-coalesce-version-must-change-on-health-state: peek() reflects the current cached state for cache key purposes', async () => {
    let currentTime = 1000
    const now = () => currentTime
    probe.mockResolvedValue(true)
    const health2 = createMergeServerHealth({
      probe,
      ttlMs: 100,
      now
    })

    // First check - succeeds, peek returns true
    await health2.check()
    expect(health2.peek()).toBe(true)

    // Second check - still cached, peek returns true (for cache key)
    currentTime = 1050
    expect(health2.peek()).toBe(true)

    // After TTL expires, probe returns false
    currentTime = 1150
    probe.mockResolvedValue(false)
    await health2.check()
    expect(health2.peek()).toBe(false)
  })
})
