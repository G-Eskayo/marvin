import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { readDismissed, dismissHelper, isHelperDismissed } from '../electron/main/helpers_dismissed.js'

function withTempDir(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'helpers-dismissed-test-'))
  try {
    return fn(join(dir, 'helpers-dismissed.json'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('readDismissed', () => {
  it('returns an empty Map when the file does not exist', () => {
    withTempDir((path) => {
      const result = readDismissed(path)
      expect(result).toEqual(new Map())
      expect(result instanceof Map).toBe(true)
    })
  })

  it('returns an empty Map when the file is corrupt', () => {
    withTempDir((path) => {
      writeFileSync(path, 'not json')
      const result = readDismissed(path)
      expect(result).toEqual(new Map())
      expect(result instanceof Map).toBe(true)
    })
  })

  it('returns an empty Map when dismissed is not an object', () => {
    withTempDir((path) => {
      writeFileSync(path, JSON.stringify({ dismissed: 'not-an-object' }))
      const result = readDismissed(path)
      expect(result).toEqual(new Map())
      expect(result instanceof Map).toBe(true)
    })
  })

  it('returns a Map with the dismissed keys and timestamps', () => {
    withTempDir((path) => {
      const t1 = Date.now()
      dismissHelper(path, 'helper-1')
      const t2 = Date.now()
      dismissHelper(path, 'helper-2')
      const result = readDismissed(path)
      expect(result instanceof Map).toBe(true)
      expect(result.has('helper-1')).toBe(true)
      expect(result.has('helper-2')).toBe(true)
      expect(result.get('helper-1')).toBeGreaterThanOrEqual(t1)
      expect(result.get('helper-2')).toBeGreaterThanOrEqual(t2)
    })
  })
})

describe('dismissHelper', () => {
  it('persists a dismissed key so a later read sees it', () => {
    withTempDir((path) => {
      const t = Date.now()
      dismissHelper(path, 'helper-1')
      const dismissed = readDismissed(path)
      expect(dismissed.has('helper-1')).toBe(true)
      expect(dismissed.get('helper-1')).toBeGreaterThanOrEqual(t)
    })
  })

  it('accumulates across calls instead of overwriting', () => {
    withTempDir((path) => {
      dismissHelper(path, 'helper-1')
      dismissHelper(path, 'helper-2')
      const dismissed = readDismissed(path)
      expect(dismissed.has('helper-1')).toBe(true)
      expect(dismissed.has('helper-2')).toBe(true)
    })
  })

  it('updates the timestamp when the same key is dismissed twice', () => {
    withTempDir((path) => {
      dismissHelper(path, 'helper-1')
      const first = readDismissed(path).get('helper-1')
      dismissHelper(path, 'helper-1')
      const second = readDismissed(path).get('helper-1')
      expect(second).toBeGreaterThanOrEqual(first)
    })
  })

  it('creates parent directories that do not exist yet', () => {
    withTempDir((path) => {
      const nested = join(path, '..', 'nested', 'helpers-dismissed.json')
      dismissHelper(nested, 'helper-1')
      expect(readDismissed(nested).has('helper-1')).toBe(true)
    })
  })

  it('rejects an empty key', () => {
    withTempDir((path) => {
      expect(() => dismissHelper(path, '')).toThrow()
    })
  })

  it('rejects a key longer than 256 characters', () => {
    withTempDir((path) => {
      expect(() => dismissHelper(path, 'x'.repeat(257))).toThrow()
    })
  })

  it('rejects a non-string key', () => {
    withTempDir((path) => {
      expect(() => dismissHelper(path, 123)).toThrow()
    })
  })
})

describe('isHelperDismissed', () => {
  it('returns true when the helper is in the dismissed set', () => {
    const dismissed = new Map([['helper-1', Date.now()]])
    expect(isHelperDismissed('helper-1', dismissed)).toBe(true)
  })

  it('returns false when the helper is not dismissed', () => {
    const dismissed = new Map([['helper-1', Date.now()]])
    expect(isHelperDismissed('helper-2', dismissed)).toBe(false)
  })

  it('returns false when dismissed is null or undefined', () => {
    expect(isHelperDismissed('helper-1', null)).toBe(false)
    expect(isHelperDismissed('helper-1', undefined)).toBe(false)
  })
})
