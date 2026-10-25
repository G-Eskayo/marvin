import { describe, it, expect } from 'vitest'
import { clampBytes, clampChunks, createTokenBucket, createBoundedMap } from '../mobile-backend/bench_limits.js'

describe('bench_limits', () => {
  it('clampBytes clamps values within range', () => {
    expect(clampBytes(50, 0, 100)).toBe(50)
    expect(clampBytes(-10, 0, 100)).toBe(0)
    expect(clampBytes(150, 0, 100)).toBe(100)
  })

  it('clampChunks enforces integer chunk counts', () => {
    expect(clampChunks(5, 1, 10)).toBe(5)
    expect(clampChunks(15.7, 1, 10)).toBe(10)
    expect(clampChunks(0.5, 1, 10)).toBe(1)
  })

  it('createTokenBucket tracks consumption over time', () => {
    let nowMs = 0
    const mockNow = () => nowMs
    const bucket = createTokenBucket({
      tokensPerSecond: 10,
      maxBurst: 20,
      now: mockNow
    })

    expect(bucket.tryConsume(10)).toBe(true)
    expect(bucket.tryConsume(15)).toBe(false)

    nowMs += 1000
    expect(bucket.tryConsume(15)).toBe(true)
    expect(bucket.tryConsume(6)).toBe(false)
  })

  it('createBoundedMap evicts oldest when full', () => {
    const map = createBoundedMap(3)
    map.set('a', 1)
    map.set('b', 2)
    map.set('c', 3)
    expect(map.size).toBe(3)

    map.set('d', 4)
    expect(map.size).toBe(3)
    expect(map.has('a')).toBe(false)
    expect(map.has('d')).toBe(true)
  })

  it('createBoundedMap updates existing keys without evicting', () => {
    const map = createBoundedMap(2)
    map.set('a', 1)
    map.set('b', 2)
    map.set('a', 10)
    expect(map.size).toBe(2)
    expect(map.get('a')).toBe(10)
  })
})
