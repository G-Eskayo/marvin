import { describe, it, expect, vi } from 'vitest'
import { detectReorders, calculateStats, runLeg, throughputMbps } from '../mobile-backend/bench_client.js'

describe('bench_client', () => {
  it('throughputMbps calculates correctly', () => {
    expect(throughputMbps(10240, 100)).toBeCloseTo(0.8192, 3)
    expect(throughputMbps(1024000, 100)).toBeCloseTo(81.92, 1)
  })

  it('detectReorders counts out-of-order chunks', () => {
    expect(detectReorders([0, 1, 2, 3])).toBe(0)
    expect(detectReorders([0, 2, 1, 3])).toBe(1)
    expect(detectReorders([3, 2, 1, 0])).toBe(3)
  })

  it('calculateStats returns mean and stddev', () => {
    const stats = calculateStats([10, 20, 30])
    expect(stats.count).toBe(3)
    expect(stats.mean).toBe(20)
    expect(stats.min).toBe(10)
    expect(stats.max).toBe(30)
  })

  it('calculateStats handles empty array', () => {
    const stats = calculateStats([])
    expect(stats.count).toBe(0)
    expect(stats.mean).toBe(0)
  })

  it('calculateStats includes percentiles', () => {
    const values = Array.from({ length: 100 }, (_, i) => i + 1)
    const stats = calculateStats(values)
    expect(stats.p50).toBeCloseTo(50, -1)
    expect(stats.p95).toBeCloseTo(95, -1)
    expect(stats.p99).toBeCloseTo(99, -1)
  })

  it('runLeg calls transport methods in sequence', async () => {
    const transport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn().mockResolvedValue({
        chunks: 10,
        totalBytes: 10240,
        elapsedMs: 100,
        ttfbMs: 5,
        throughputMbps: 0.8192
      })
    }

    const result = await runLeg('test-leg', transport, {
      numPings: 2,
      numStreams: 1
    })

    expect(transport.connect).toHaveBeenCalled()
    expect(transport.ping).toHaveBeenCalledTimes(2)
    expect(transport.stream).toHaveBeenCalledTimes(1)
    expect(transport.disconnect).toHaveBeenCalled()
    expect(result.pings.length).toBe(2)
    expect(result.streams.length).toBe(1)
  })

  it('runLeg retries on ping failure', async () => {
    const transport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi
        .fn()
        .mockRejectedValueOnce(new Error('ping failed'))
        .mockResolvedValueOnce({ ttfbMs: 10 })
        .mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn().mockResolvedValue({
        chunks: 10,
        totalBytes: 10240,
        elapsedMs: 100,
        ttfbMs: 5,
        throughputMbps: 0.8192
      })
    }

    const result = await runLeg('test-leg', transport, {
      numPings: 2,
      numStreams: 0
    })

    // First ping fails but retries successfully, second ping succeeds immediately
    expect(result.errors.length).toBe(0)
    expect(result.pings.length).toBe(2)
  })

  it('runLeg reconnects after final ping failure', async () => {
    const transport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockRejectedValue(new Error('ping failed')),
      stream: vi.fn()
    }

    const result = await runLeg('test-leg', transport, {
      numPings: 1,
      numStreams: 0
    })

    expect(transport.disconnect).toHaveBeenCalled()
    expect(transport.connect).toHaveBeenCalledTimes(2)
  })

  it('runLeg retries on stream failure with bounded maxRetries', async () => {
    const transport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi
        .fn()
        .mockRejectedValueOnce(new Error('stream failed'))
        .mockResolvedValueOnce({
          chunks: 10,
          totalBytes: 10240,
          elapsedMs: 100,
          ttfbMs: 5,
          chunkSequence: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        })
    }

    const result = await runLeg('test-leg', transport, {
      numPings: 0,
      numStreams: 1,
      maxRetries: 1
    })

    expect(result.streams.length).toBe(1)
    expect(result.errors.length).toBe(0)
    expect(transport.stream).toHaveBeenCalledTimes(2)
  })

  it('runLeg tracks reorders from chunkSequence', async () => {
    const transport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn().mockResolvedValue({
        chunks: 4,
        totalBytes: 4096,
        elapsedMs: 100,
        ttfbMs: 5,
        chunkSequence: [0, 2, 1, 3]
      })
    }

    const result = await runLeg('test-leg', transport, {
      numPings: 0,
      numStreams: 1
    })

    expect(result.reorders).toBe(1)
  })
})
