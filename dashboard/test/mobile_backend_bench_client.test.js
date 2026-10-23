import { describe, it, expect } from 'vitest'
import { calculateStats, detectReorders, runLeg } from '../mobile-backend/bench_client.js'

describe('bench_client stats', () => {
  describe('calculateStats', () => {
    it('calculates correct statistics from a clean sequence', () => {
      const sequence = [
        { seqn: 1, rtt: 10 },
        { seqn: 2, rtt: 12 },
        { seqn: 3, rtt: 11 },
        { seqn: 4, rtt: 13 }
      ]
      const stats = calculateStats(sequence)
      expect(stats.lossPct).toBe(0)
      expect(stats.reorderCount).toBe(0)
      expect(stats.avgRttMs).toBeCloseTo(11.5)
    })

    it('calculates loss percentage from gaps in sequence', () => {
      const sequence = [
        { seqn: 1, rtt: 10 },
        { seqn: 3, rtt: 11 },
        { seqn: 5, rtt: 12 }
      ]
      const stats = calculateStats(sequence)
      expect(stats.lossPct).toBeCloseTo(40)
      expect(stats.reorderCount).toBe(0)
    })

    it('detects out-of-order packets', () => {
      const sequence = [
        { seqn: 1, rtt: 10 },
        { seqn: 3, rtt: 11 },
        { seqn: 2, rtt: 12 },
        { seqn: 4, rtt: 13 }
      ]
      const stats = calculateStats(sequence)
      expect(stats.reorderCount).toBe(1)
    })

    it('handles completely reordered sequence [1,4,2,3]', () => {
      const sequence = [
        { seqn: 1, rtt: 10 },
        { seqn: 4, rtt: 13 },
        { seqn: 2, rtt: 11 },
        { seqn: 3, rtt: 12 }
      ]
      const stats = calculateStats(sequence)
      expect(stats.lossPct).toBe(0)
      expect(stats.reorderCount).toBe(2)
    })

    it('computes min/max from full sequence not just first/last', () => {
      const sequence = [
        { seqn: 5 },
        { seqn: 1 },
        { seqn: 10 },
        { seqn: 3 }
      ]
      const stats = calculateStats(sequence)
      const expected = 10 - 1 + 1
      expect(stats.lossPct).toBeCloseTo((expected - 4) / expected * 100)
    })

    it('handles sequence with gaps and reorders', () => {
      const sequence = [
        { seqn: 1 },
        { seqn: 5 },
        { seqn: 3 },
        { seqn: 7 }
      ]
      const stats = calculateStats(sequence)
      expect(stats.reorderCount).toBe(1)
    })

    it('handles empty sequence', () => {
      const stats = calculateStats([])
      expect(stats.lossPct).toBe(0)
      expect(stats.reorderCount).toBe(0)
      expect(stats.avgRttMs).toBe(0)
    })

    it('handles single packet', () => {
      const sequence = [{ seqn: 1, rtt: 10 }]
      const stats = calculateStats(sequence)
      expect(stats.lossPct).toBe(0)
      expect(stats.reorderCount).toBe(0)
      expect(stats.avgRttMs).toBe(10)
    })
  })

  describe('detectReorders', () => {
    it('returns 0 for in-order sequence', () => {
      const sequence = [
        { seqn: 1 },
        { seqn: 2 },
        { seqn: 3 }
      ]
      expect(detectReorders(sequence)).toBe(0)
    })

    it('counts packets arriving after a higher seqn', () => {
      const sequence = [
        { seqn: 1 },
        { seqn: 3 },
        { seqn: 2 },
        { seqn: 4 }
      ]
      expect(detectReorders(sequence)).toBe(1)
    })

    it('counts multiple reorders', () => {
      const sequence = [
        { seqn: 1 },
        { seqn: 4 },
        { seqn: 2 },
        { seqn: 3 }
      ]
      expect(detectReorders(sequence)).toBe(2)
    })

    it('handles empty sequence', () => {
      expect(detectReorders([])).toBe(0)
    })
  })

  describe('runLeg transport contract', () => {
    it('accepts transport returning { bytes, ttfbMs, sequence }', async () => {
      const mockTransport = {
        async connect() {},
        async disconnect() {},
        async ping() {},
        async stream() {
          return {
            bytes: 10240,
            ttfbMs: 50,
            sequence: [
              { seqn: 0 },
              { seqn: 1 },
              { seqn: 2 }
            ]
          }
        }
      }

      const result = await runLeg('test-leg', mockTransport)
      expect(result.name).toBe('test-leg')
      expect(result.ttfb).toBe(50)
      expect(result.lossPct).toBe(0)
      expect(result.rtt).not.toBeNull()
    })

    it('calculates throughput from bytes and stream duration', async () => {
      const mockTransport = {
        async connect() {},
        async disconnect() {},
        async ping() {},
        async stream() {
          return {
            bytes: 1024 * 1024,
            ttfbMs: 50,
            sequence: []
          }
        }
      }

      const result = await runLeg('test-leg', mockTransport)
      expect(result.name).toBe('test-leg')
      expect(result.ttfb).toBe(50)
    })

    it('uses sequence from transport for stats', async () => {
      const mockTransport = {
        async connect() {},
        async disconnect() {},
        async ping() {},
        async stream() {
          return {
            bytes: 10240,
            ttfbMs: 50,
            sequence: [
              { seqn: 1 },
              { seqn: 4 },
              { seqn: 2 },
              { seqn: 3 }
            ]
          }
        }
      }

      const result = await runLeg('test-leg', mockTransport)
      expect(result.lossPct).toBe(0)
      expect(result.reorderCount).toBe(2)
    })

    it('calculates throughput correctly in Mbps', async () => {
      const mockTransport = {
        async connect() {},
        async disconnect() {},
        async ping() {},
        async stream() {
          return {
            bytes: 125000,
            ttfbMs: 50,
            sequence: []
          }
        }
      }

      let timeMs = 0
      const mockNow = () => timeMs

      const result = await runLeg('test-leg', mockTransport, {
        now: () => {
          timeMs += 100
          return timeMs
        }
      })

      expect(result.throughputMbps).toBeGreaterThan(0)
      const expectedMbps = 125000 * 8 / (0.1 * 1e6)
      expect(result.throughputMbps).toBeCloseTo(expectedMbps, 0)
    })

    it('accepts injectable now function', async () => {
      const mockTransport = {
        async connect() {},
        async disconnect() {},
        async ping() {},
        async stream() {
          return {
            bytes: 10240,
            ttfbMs: 50,
            sequence: []
          }
        }
      }

      let currentTime = 1000
      const mockNow = () => {
        const time = currentTime
        currentTime += 50
        return time
      }

      const result = await runLeg('test-leg', mockTransport, { now: mockNow })
      expect(result.rtt).toBeGreaterThan(0)
      expect(result.name).toBe('test-leg')
    })
  })
})
