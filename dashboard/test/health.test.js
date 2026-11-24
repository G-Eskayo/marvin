import { requestHealthSweep } from '../electron/main/health.js'
import { describe, it, expect, vi, beforeEach } from 'vitest'

describe('health.js', () => {
  describe('requestHealthSweep', () => {
    let mockExecFileAsync

    beforeEach(() => {
      mockExecFileAsync = vi.fn().mockResolvedValue(undefined)
    })

    it('calls runHealthCheckNow once on first request (de-dup)', async () => {
      const p1 = requestHealthSweep(mockExecFileAsync)
      const p2 = requestHealthSweep(mockExecFileAsync)

      await Promise.all([p1, p2])
      expect(mockExecFileAsync).toHaveBeenCalledTimes(1)
    })

    it('returns quickly when a sweep is already in-flight', async () => {
      let resolveFirst
      const longPromise = new Promise((resolve) => {
        resolveFirst = resolve
      })
      mockExecFileAsync.mockReturnValue(longPromise)

      const p1 = requestHealthSweep(mockExecFileAsync)
      const start = Date.now()
      const p2 = requestHealthSweep(mockExecFileAsync)
      const p2Time = Date.now() - start

      // p2 should return almost immediately
      expect(p2Time).toBeLessThan(100)

      // Now resolve the first one
      resolveFirst()
      await Promise.all([p1, p2])
    }, { timeout: 10000 })

    it('clears in-flight state after sweep completes', async () => {
      await requestHealthSweep(mockExecFileAsync)

      // Reset mock to verify new call happens
      mockExecFileAsync.mockClear()

      // Second request should trigger a new sweep
      await requestHealthSweep(mockExecFileAsync)
      expect(mockExecFileAsync).toHaveBeenCalledTimes(1)
    })

    it('clears in-flight state even when sweep fails', async () => {
      mockExecFileAsync.mockRejectedValueOnce(new Error('sweep failed'))

      await requestHealthSweep(mockExecFileAsync)
      // Error is swallowed, function returns without throwing

      // Reset mock
      mockExecFileAsync.mockClear().mockResolvedValueOnce(undefined)

      // Next request should proceed normally
      await requestHealthSweep(mockExecFileAsync)
      expect(mockExecFileAsync).toHaveBeenCalledTimes(1)
    })
  })
})
