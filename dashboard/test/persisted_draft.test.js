import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readStored, writeStored, clearStored } from '../src/lib/persisted_draft.js'

// Mock localStorage (must properly handle empty strings, not coerce to null)
const mockStorage = new Map()
const mockLocalStorage = {
  getItem: (key) => mockStorage.has(key) ? mockStorage.get(key) : null,
  setItem: (key, value) => mockStorage.set(key, value),
  removeItem: (key) => mockStorage.delete(key),
  clear: () => mockStorage.clear()
}

describe('persisted_draft', () => {
  beforeEach(() => {
    mockStorage.clear()
    global.localStorage = mockLocalStorage
    vi.clearAllMocks()
  })

  describe('readStored', () => {
    it('returns stored string value', () => {
      const value = 'hello world'
      localStorage.setItem('test-key', value)
      expect(readStored('test-key')).toBe(value)
    })

    it('returns fallback when key not present', () => {
      const fallback = 'default'
      expect(readStored('missing-key', fallback)).toBe(fallback)
    })

    it('returns default fallback when not provided', () => {
      expect(readStored('missing-key')).toBe('')
    })

    it('returns null when explicitly stored as null', () => {
      localStorage.setItem('null-key', null)
      expect(readStored('null-key', 'default')).toBe('default')
    })

    it('returns fallback when localStorage is unavailable', () => {
      const originalLS = global.localStorage
      delete global.localStorage
      expect(readStored('any', 'fallback')).toBe('fallback')
      global.localStorage = originalLS
    })

    it('handles SecurityError gracefully', () => {
      const originalGetItem = localStorage.getItem
      localStorage.getItem = vi.fn(() => {
        const err = new Error('SecurityError')
        err.name = 'SecurityError'
        throw err
      })
      expect(readStored('key', 'fallback')).toBe('fallback')
      localStorage.getItem = originalGetItem
    })
  })

  describe('writeStored', () => {
    it('stores value as string', () => {
      const value = 'test-value'
      writeStored('test-key', value)
      expect(localStorage.getItem('test-key')).toBe(value)
    })

    it('distinguishes between empty string and missing key', () => {
      writeStored('empty', '')
      writeStored('filled', 'value')

      // Empty string was stored (it's not missing)
      expect(localStorage.getItem('filled')).toBe('value')
      // Fallback applies when key is missing
      expect(readStored('missing', 'default')).toBe('default')
      // But for empty string, the fallback doesn't apply
      const emptyResult = readStored('empty', 'default')
      expect(emptyResult).toBe('')
    })

    it('handles quota exceeded gracefully', () => {
      const originalSetItem = localStorage.setItem
      localStorage.setItem = vi.fn(() => {
        const err = new Error('QuotaExceededError')
        err.name = 'QuotaExceededError'
        throw err
      })
      expect(() => writeStored('key', 'value')).not.toThrow()
      localStorage.setItem = originalSetItem
    })

    it('handles security errors gracefully', () => {
      const originalSetItem = localStorage.setItem
      localStorage.setItem = vi.fn(() => {
        const err = new Error('SecurityError')
        err.name = 'SecurityError'
        throw err
      })
      expect(() => writeStored('key', 'value')).not.toThrow()
      localStorage.setItem = originalSetItem
    })

    it('handles undefined localStorage gracefully', () => {
      const originalLS = global.localStorage
      delete global.localStorage
      expect(() => writeStored('key', 'value')).not.toThrow()
      global.localStorage = originalLS
    })
  })

  describe('clearStored', () => {
    it('removes stored value', () => {
      localStorage.setItem('test-key', 'value')
      clearStored('test-key')
      expect(localStorage.getItem('test-key')).toBeNull()
    })

    it('handles missing key silently', () => {
      expect(() => clearStored('missing-key')).not.toThrow()
    })
  })
})
