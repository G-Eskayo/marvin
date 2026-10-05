import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readToolUsage, isStale, failureRate } from '../electron/main/tool_usage.js'

const withDir = (fn) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'tu-'))
  try {
    return fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('readToolUsage / isStale', () => {
  it('reads the scan or returns null for a missing/corrupt file', () =>
    withDir((dir) => {
      const f = path.join(dir, 'u.json')
      expect(readToolUsage(f)).toBeNull()
      writeFileSync(f, '{bad')
      expect(readToolUsage(f)).toBeNull()
      writeFileSync(f, JSON.stringify({ generated_at: new Date().toISOString(), tools: [] }))
      expect(readToolUsage(f).tools).toEqual([])
    }))

  it('is stale when missing, unparseable or older than the max age', () => {
    expect(isStale(null)).toBe(true)
    expect(isStale({ generated_at: 'nope' })).toBe(true)
    expect(isStale({ generated_at: new Date().toISOString() }, 60_000)).toBe(false)
    expect(isStale({ generated_at: new Date(Date.now() - 120_000).toISOString() }, 60_000)).toBe(true)
  })
})

describe('failureRate', () => {
  it('counts errors and invalid calls against all calls, and is 0 for no calls', () => {
    expect(failureRate({ calls: 10, error: 2, invalid: 1 })).toBeCloseTo(0.3)
    expect(failureRate({ calls: 0, error: 0, invalid: 0 })).toBe(0)
  })
})
