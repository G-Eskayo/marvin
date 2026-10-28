import { describe, it, expect } from 'vitest'
import { readSaved, writeSaved, ageText } from '../src/lib/saved_state.js'

describe('readSaved', () => {
  it('returns null when storage is undefined', () => {
    expect(readSaved(undefined, 'key')).toBe(null)
  })

  it('returns null when storage is null', () => {
    expect(readSaved(null, 'key')).toBe(null)
  })

  it('returns null on corrupt JSON', () => {
    const storage = {
      getItem: () => 'not valid json {'
    }
    expect(readSaved(storage, 'key')).toBe(null)
  })

  it('returns null when the parsed blob is missing `at` (number)', () => {
    const storage = {
      getItem: () => JSON.stringify({ value: { some: 'data' } })
    }
    expect(readSaved(storage, 'key')).toBe(null)
  })

  it('returns null when the parsed blob is missing `value`', () => {
    const storage = {
      getItem: () => JSON.stringify({ at: Date.now() })
    }
    expect(readSaved(storage, 'key')).toBe(null)
  })

  it('returns null when `at` is not a number', () => {
    const storage = {
      getItem: () => JSON.stringify({ at: '123456', value: { data: 'test' } })
    }
    expect(readSaved(storage, 'key')).toBe(null)
  })

  it('returns the parsed data when blob is valid', () => {
    const now = Date.now()
    const data = { boards: [{ repo: 'o/r', name: 'Test' }] }
    const storage = {
      getItem: () => JSON.stringify({ at: now, value: data })
    }
    const result = readSaved(storage, 'key')
    expect(result).toEqual({ at: now, value: data })
  })

  it('uses the provided key to fetch from storage', () => {
    let fetchedKey = null
    const storage = {
      getItem: (k) => {
        fetchedKey = k
        return JSON.stringify({ at: Date.now(), value: {} })
      }
    }
    readSaved(storage, 'my-special-key')
    expect(fetchedKey).toBe('my-special-key')
  })
})

describe('writeSaved', () => {
  it('writes valid data to storage with current timestamp', () => {
    const now = Date.now()
    let written = null
    const storage = {
      setItem: (k, v) => {
        written = JSON.parse(v)
      }
    }
    const data = { prs: [{ number: 1, title: 'Test' }] }
    writeSaved(storage, 'prs-key', data, now)
    expect(written).toEqual({ at: now, value: data })
  })

  it('swallows a storage.setItem that throws on quota exceeded', () => {
    const storage = {
      setItem: () => {
        throw new Error('QuotaExceededError')
      }
    }
    expect(() => writeSaved(storage, 'key', { data: 'test' })).not.toThrow()
  })

  it('swallows a storage that throws for any reason', () => {
    const storage = {
      setItem: () => {
        throw new Error('Some other error')
      }
    }
    expect(() => writeSaved(storage, 'key', { data: 'test' })).not.toThrow()
  })

  it('swallows a storage that is undefined', () => {
    expect(() => writeSaved(undefined, 'key', { data: 'test' })).not.toThrow()
  })

  it('swallows a storage that is null', () => {
    expect(() => writeSaved(null, 'key', { data: 'test' })).not.toThrow()
  })

  it('uses the provided timestamp when supplied', () => {
    const customTime = 1000000000
    let written = null
    const storage = {
      setItem: (k, v) => {
        written = JSON.parse(v)
      }
    }
    writeSaved(storage, 'key', { data: 'test' }, customTime)
    expect(written.at).toBe(customTime)
  })

  it('uses Date.now() as default when no timestamp supplied', () => {
    let written = null
    const storage = {
      setItem: (k, v) => {
        written = JSON.parse(v)
      }
    }
    const before = Date.now()
    writeSaved(storage, 'key', { data: 'test' })
    const after = Date.now()
    expect(written.at).toBeGreaterThanOrEqual(before)
    expect(written.at).toBeLessThanOrEqual(after)
  })
})

describe('ageText', () => {
  const baseTime = Date.parse('2026-10-08T12:00:00Z')

  it('returns "updated just now" for times < 60 s ago', () => {
    expect(ageText(baseTime - 0, baseTime)).toBe('updated just now')
    expect(ageText(baseTime - 30 * 1000, baseTime)).toBe('updated just now')
    expect(ageText(baseTime - 59 * 1000, baseTime)).toBe('updated just now')
  })

  it('returns "updated Xm ago" for times < 60 min ago', () => {
    expect(ageText(baseTime - 60 * 1000, baseTime)).toBe('updated 1 min ago')
    expect(ageText(baseTime - 5 * 60 * 1000, baseTime)).toBe('updated 5 min ago')
    expect(ageText(baseTime - 59 * 60 * 1000, baseTime)).toBe('updated 59 min ago')
  })

  it('returns "updated Xh ago" for times < 24 hours ago', () => {
    expect(ageText(baseTime - 60 * 60 * 1000, baseTime)).toBe('updated 1 h ago')
    expect(ageText(baseTime - 2 * 3600 * 1000, baseTime)).toBe('updated 2 h ago')
    expect(ageText(baseTime - 23 * 3600 * 1000, baseTime)).toBe('updated 23 h ago')
  })

  it('returns "updated Xd ago" for times < 7+ days ago, with singular/plural', () => {
    expect(ageText(baseTime - 86400 * 1000, baseTime)).toBe('updated 1 day ago')
    expect(ageText(baseTime - 2 * 86400 * 1000, baseTime)).toBe('updated 2 days ago')
    expect(ageText(baseTime - 6 * 86400 * 1000, baseTime)).toBe('updated 6 days ago')
  })

  it('handles boundary edge cases correctly', () => {
    // just over 60 s boundary
    expect(ageText(baseTime - 61 * 1000, baseTime)).toBe('updated 1 min ago')
    // just under 60 min boundary
    expect(ageText(baseTime - (60 * 60 - 1) * 1000, baseTime)).toBe('updated 59 min ago')
    // exactly at 60 min boundary
    expect(ageText(baseTime - 60 * 60 * 1000, baseTime)).toBe('updated 1 h ago')
  })

  it('uses Date.now() as default when no second argument', () => {
    const recentTime = Date.now() - 5 * 1000
    const result = ageText(recentTime)
    expect(result).toBe('updated just now')
  })

  it('clamps negative time differences to zero', () => {
    const futureTime = baseTime + 1000
    const result = ageText(futureTime, baseTime)
    expect(result).toBe('updated just now')
  })
})
