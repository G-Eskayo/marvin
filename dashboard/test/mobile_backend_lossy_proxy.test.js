import { describe, it, expect, vi } from 'vitest'
import { createLossyProxy } from '../mobile-backend/transports/lossy_proxy.js'

describe('lossy_proxy transport', () => {
  it('performs adjacent-swap reordering on chunkSequence', async () => {
    const mockTransport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn().mockResolvedValue({
        totalBytes: 10240,
        elapsedMs: 100,
        chunks: 10,
        chunkSequence: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
      })
    }

    const proxy = createLossyProxy(mockTransport, {
      lossRate: 0,
      reorderRate: 100, // Always reorder
      seed: 42
    })

    const result = await proxy.stream(10)

    // With reorderRate: 100, should always reorder
    // Verify that adjacent swap happened
    const sequence = result.chunkSequence
    expect(sequence).toBeDefined()
    expect(Array.isArray(sequence)).toBe(true)

    // Check that an adjacent pair was swapped
    let swapped = false
    for (let i = 0; i < sequence.length - 1; i++) {
      if (sequence[i] > sequence[i + 1]) {
        swapped = true
        break
      }
    }
    expect(swapped).toBe(true)
  })

  it('preserves totalBytes and chunks on reorder', async () => {
    const mockTransport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn().mockResolvedValue({
        totalBytes: 10240,
        elapsedMs: 100,
        chunks: 10,
        chunkSequence: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
      })
    }

    const proxy = createLossyProxy(mockTransport, {
      lossRate: 0,
      reorderRate: 100,
      seed: 42
    })

    const result = await proxy.stream(10)

    expect(result.totalBytes).toBe(10240)
    expect(result.chunks).toBe(10)
  })

  it('does not reorder when chunkSequence is missing or too small', async () => {
    const mockTransport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn().mockResolvedValue({
        totalBytes: 1024,
        elapsedMs: 100,
        chunks: 1
      })
    }

    const proxy = createLossyProxy(mockTransport, {
      lossRate: 0,
      reorderRate: 100,
      seed: 42
    })

    const result = await proxy.stream(1)

    expect(result.chunkSequence).toBeUndefined()
  })

  it('seeded random produces deterministic reordering', async () => {
    const mockTransport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn().mockResolvedValue({
        totalBytes: 10240,
        elapsedMs: 100,
        chunks: 10,
        chunkSequence: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
      })
    }

    const proxy1 = createLossyProxy(mockTransport, {
      lossRate: 0,
      reorderRate: 100,
      seed: 42
    })

    const result1 = await proxy1.stream(10)

    const proxy2 = createLossyProxy(mockTransport, {
      lossRate: 0,
      reorderRate: 100,
      seed: 42
    })

    const result2 = await proxy2.stream(10)

    expect(result1.chunkSequence).toEqual(result2.chunkSequence)
  })

  it('different seeds produce different reordering', async () => {
    const mockTransport = {
      connect: vi.fn().mockResolvedValue({}),
      disconnect: vi.fn().mockResolvedValue({}),
      ping: vi.fn().mockResolvedValue({ ttfbMs: 10 }),
      stream: vi.fn(async () => ({
        totalBytes: 10240,
        elapsedMs: 100,
        chunks: 10,
        chunkSequence: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
      }))
    }

    const proxy1 = createLossyProxy(mockTransport, {
      lossRate: 0,
      reorderRate: 100,
      seed: 42
    })

    const result1 = await proxy1.stream(10)

    const proxy2 = createLossyProxy(mockTransport, {
      lossRate: 0,
      reorderRate: 100,
      seed: 99
    })

    const result2 = await proxy2.stream(10)

    expect(result1.chunkSequence).not.toEqual(result2.chunkSequence)
  })
})
