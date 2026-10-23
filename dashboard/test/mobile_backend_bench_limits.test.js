import { describe, it, expect } from 'vitest'
import { clampBytes, clampChunks, createTokenBucket, createBoundedMap } from '../mobile-backend/bench_limits.js'

describe('bench_limits', () => {
  describe('clampBytes', () => {
    it('allows small payloads', () => {
      expect(clampBytes(1000, 10 * 1024 * 1024)).toBe(1000)
    })

    it('rejects payloads larger than max', () => {
      const result = clampBytes(11 * 1024 * 1024, 10 * 1024 * 1024)
      expect(result).toBeInstanceOf(Error)
      expect(result.code).toBe('PAYLOAD_TOO_LARGE')
    })

    it('allows payloads exactly at max', () => {
      const max = 10 * 1024 * 1024
      expect(clampBytes(max, max)).toBe(max)
    })

    it('returns error with appropriate statusCode', () => {
      const result = clampBytes(11 * 1024 * 1024, 10 * 1024 * 1024)
      expect(result.statusCode).toBe(413)
    })
  })

  describe('clampChunks', () => {
    it('returns valid chunk count', () => {
      expect(clampChunks('5')).toBe(5)
    })

    it('clamps to default when not specified', () => {
      expect(clampChunks(undefined, 10)).toBe(10)
    })

    it('rejects negative values', () => {
      const result = clampChunks('-5')
      expect(result).toBeInstanceOf(Error)
      expect(result.statusCode).toBe(400)
    })

    it('rejects non-numeric values', () => {
      const result = clampChunks('abc')
      expect(result).toBeInstanceOf(Error)
      expect(result.statusCode).toBe(400)
    })

    it('clamps to maximum', () => {
      const result = clampChunks('10000', 10, 100)
      expect(result).toBe(100)
    })

    it('handles zero', () => {
      const result = clampChunks('0')
      expect(result).toBeInstanceOf(Error)
      expect(result.statusCode).toBe(400)
    })

    it('handles floating point by truncating', () => {
      expect(clampChunks('5.7')).toBe(5)
    })
  })

  describe('createTokenBucket', () => {
    it('allows requests within rate limit', () => {
      const bucket = createTokenBucket({
        tokensPerSecond: 10,
        maxBurst: 10
      })

      for (let i = 0; i < 10; i++) {
        expect(bucket.tryConsume()).toBe(true)
      }
    })

    it('rejects requests exceeding rate limit', () => {
      const bucket = createTokenBucket({
        tokensPerSecond: 2,
        maxBurst: 2
      })

      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(false)
    })

    it('refills tokens over time', async () => {
      const bucket = createTokenBucket({
        tokensPerSecond: 10,
        maxBurst: 2
      })

      // Consume all tokens
      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(false)

      // Wait 200ms: 10 tokens/sec * 0.2s = 2 new tokens
      await new Promise(resolve => setTimeout(resolve, 200))

      // Should be able to consume again
      expect(bucket.tryConsume()).toBe(true)
    })

    it('caps tokens at maxBurst', async () => {
      const bucket = createTokenBucket({
        tokensPerSecond: 100, // High refill rate
        maxBurst: 3
      })

      // Wait 1 second: would refill 100 tokens, but capped at 3
      await new Promise(resolve => setTimeout(resolve, 1000))

      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(false)
    })

    it('supports per-peer buckets', () => {
      const buckets = new Map()

      function getBucket(peerId) {
        if (!buckets.has(peerId)) {
          buckets.set(peerId, createTokenBucket({
            tokensPerSecond: 5,
            maxBurst: 5
          }))
        }
        return buckets.get(peerId)
      }

      const peer1 = getBucket('peer-a')
      const peer2 = getBucket('peer-b')

      // Each peer has independent limits
      for (let i = 0; i < 5; i++) {
        expect(peer1.tryConsume()).toBe(true)
        expect(peer2.tryConsume()).toBe(true)
      }

      // Both should be rate-limited now
      expect(peer1.tryConsume()).toBe(false)
      expect(peer2.tryConsume()).toBe(false)
    })

    it('accepts injectable now function', () => {
      let currentTime = 1000
      const mockNow = () => currentTime

      const bucket = createTokenBucket({
        tokensPerSecond: 10,
        maxBurst: 2,
        now: mockNow
      })

      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(false)

      // Advance time by 100ms: 10 tokens/sec * 0.1s = 1 new token
      currentTime = 1100
      expect(bucket.tryConsume()).toBe(true)
    })

    it('uses injected now for refill timing', () => {
      let currentTime = 0
      const mockNow = () => currentTime

      const bucket = createTokenBucket({
        tokensPerSecond: 10,
        maxBurst: 1,
        now: mockNow
      })

      expect(bucket.tryConsume()).toBe(true)
      expect(bucket.tryConsume()).toBe(false)

      // Advance time by 100ms: 10 tokens/sec * 0.1s = 1 new token
      currentTime = 100
      expect(bucket.tryConsume()).toBe(true)
    })
  })

  describe('createBoundedMap', () => {
    it('exposes size getter', () => {
      const map = createBoundedMap(10)
      expect(map.size).toBe(0)

      map.set('key1', 'value1')
      expect(map.size).toBe(1)

      map.set('key2', 'value2')
      expect(map.size).toBe(2)
    })

    it('maintains correct size after eviction', () => {
      const map = createBoundedMap(3)

      map.set('key1', 'value1')
      map.set('key2', 'value2')
      map.set('key3', 'value3')
      expect(map.size).toBe(3)

      map.set('key4', 'value4')
      expect(map.size).toBe(3)

      expect(map.has('key1')).toBe(false)
      expect(map.has('key4')).toBe(true)
    })

    it('allows direct testing of bounded map', () => {
      const map = createBoundedMap(5)

      for (let i = 0; i < 10; i++) {
        map.set(`key${i}`, `value${i}`)
      }

      expect(map.size).toBeLessThanOrEqual(5)
      expect(map.size).toBe(5)
    })
  })
})
