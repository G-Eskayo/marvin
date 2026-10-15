import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readSort, writeSort, sortRows, paginate } from '../src/lib/needs_you_view.js'

const mockRows = [
  { number: 1, title: 'T1', repo: 'A/B', projectRepo: 'A/B', unblocks: { count: 5 }, priority: 'p0', ageDays: 10 },
  { number: 2, title: 'T2', repo: 'A/B', projectRepo: 'A/B', unblocks: { count: 3 }, priority: 'p1', ageDays: 5 },
  { number: 3, title: 'T3', repo: 'C/D', projectRepo: 'C/D', unblocks: { count: 3 }, priority: 'p2', ageDays: 20 },
  { number: 4, title: 'T4', repo: 'A/B', projectRepo: 'A/B', unblocks: { count: 1 }, priority: null, ageDays: 2 },
  { number: 5, title: 'T5', repo: 'C/D', projectRepo: 'C/D', unblocks: { count: 0 }, priority: 'p0', ageDays: 15 },
  { number: 6, title: 'T6', repo: 'A/B', projectRepo: 'C/D', unblocks: { count: 0 }, priority: null, ageDays: 1 }
]

describe('needs_you_view', () => {
  describe('readSort and writeSort', () => {
    it('returns default sort if nothing is saved', () => {
      const store = {}
      const storage = {
        getItem: (k) => store[k],
        setItem: (k, v) => { store[k] = v }
      }
      expect(readSort(storage)).toBe('unblocks')
    })

    it('returns default if storage is null', () => {
      expect(readSort(null)).toBe('unblocks')
    })

    it('returns saved sort if valid', () => {
      const store = {}
      const storage = {
        getItem: (k) => store[k],
        setItem: (k, v) => { store[k] = v }
      }
      writeSort(storage, 'priority')
      expect(readSort(storage)).toBe('priority')
    })

    it('returns default if saved sort is invalid', () => {
      const store = { 'activity.needsYou.sort': 'invalid' }
      const storage = {
        getItem: (k) => store[k],
        setItem: (k, v) => { store[k] = v }
      }
      expect(readSort(storage)).toBe('unblocks')
    })

    it('throws on invalid sort to writeSort', () => {
      const store = {}
      const storage = {
        getItem: (k) => store[k],
        setItem: (k, v) => { store[k] = v }
      }
      expect(() => writeSort(storage, 'invalid')).toThrow()
    })

    it('falls back to default if storage throws on read', () => {
      const storage = {
        getItem: () => { throw new Error('quota exceeded') },
        setItem: () => {}
      }
      expect(readSort(storage)).toBe('unblocks')
    })

    it('silently fails if storage throws on write', () => {
      const storage = {
        getItem: () => null,
        setItem: () => { throw new Error('quota exceeded') }
      }
      expect(() => writeSort(storage, 'priority')).not.toThrow()
    })

    it('persists sort choice across reads', () => {
      const mockStore = {}
      const storage = {
        getItem: (k) => mockStore[k],
        setItem: (k, v) => { mockStore[k] = v }
      }
      writeSort(storage, 'priority')
      expect(readSort(storage)).toBe('priority')
    })
  })

  describe('sortRows', () => {
    it('unblocks sort is a pass-through (backend already sorted)', () => {
      const sorted = sortRows(mockRows, 'unblocks')
      expect(sorted).toBe(mockRows)
    })

    it('priority sort: by p0/p1/p2, nulls last, tiebreak by age descending', () => {
      const sorted = sortRows(mockRows, 'priority')
      // p0: [5 (age 15), 1 (age 10)], p1: [2], p2: [3], null: [4 (age 2), 6 (age 1)]
      expect(sorted.map((r) => r.number)).toEqual([5, 1, 2, 3, 4, 6])
    })

    it('oldest sort: by ageDays descending', () => {
      const sorted = sortRows(mockRows, 'oldest')
      expect(sorted.map((r) => r.number)).toEqual([3, 5, 1, 2, 4, 6])
    })

    it('project sort: by projectRepo alphanumeric, tiebreak by unblocks descending', () => {
      const sorted = sortRows(mockRows, 'project')
      // A/B first (1, 2, 4), then C/D (3, 5, 6)
      expect(sorted.map((r) => r.number)).toEqual([1, 2, 4, 3, 5, 6])
    })

    it('defaults to unblocks if sort is invalid', () => {
      const sorted = sortRows(mockRows, 'invalid')
      expect(sorted).toBe(mockRows)
    })

    it('does not mutate the input array', () => {
      const input = [...mockRows]
      sortRows(mockRows, 'priority')
      expect(mockRows).toEqual(input)
    })

    it('handles malformed priorities without producing NaN: falls back to lowest bucket', () => {
      const malformed = [
        { number: 1, priority: 'p0', ageDays: 10 },
        { number: 2, priority: 'p99', ageDays: 20 }, // invalid priority
        { number: 3, priority: 'p1', ageDays: 5 },
        { number: 4, priority: null, ageDays: 3 }
      ]
      const sorted = sortRows(malformed, 'priority')
      // p0: [1], p1: [3], invalid/null: [2 (age 20), 4 (age 3)] — malformed priorities fall to the lowest bucket
      expect(sorted.map((r) => r.number)).toEqual([1, 3, 2, 4])
    })
  })

  describe('paginate', () => {
    it('splits rows into pages of 5', () => {
      const { pageRows, pageCount, page } = paginate(mockRows, 1)
      expect(pageRows).toHaveLength(5)
      expect(pageCount).toBe(2)
      expect(page).toBe(1)
    })

    it('returns the second page correctly', () => {
      const { pageRows } = paginate(mockRows, 2)
      expect(pageRows).toHaveLength(1)
      expect(pageRows[0].number).toBe(6)
    })

    it('clamps page to valid range [1, pageCount]', () => {
      expect(paginate(mockRows, 0).page).toBe(1)
      expect(paginate(mockRows, 3).page).toBe(2)
    })

    it('handles empty rows: pageCount=1, page=1', () => {
      const { pageCount, page } = paginate([], 1)
      expect(pageCount).toBe(1)
      expect(page).toBe(1)
    })

    it('supports custom pageSize', () => {
      const { pageRows, pageCount } = paginate(mockRows, 1, 2)
      expect(pageRows).toHaveLength(2)
      expect(pageCount).toBe(3)
    })

    it('page 0 clamps to page 1', () => {
      const { pageRows } = paginate(mockRows, 0, 5)
      expect(pageRows[0].number).toBe(1)
    })

    it('page beyond pageCount clamps to last page', () => {
      const { pageRows, page } = paginate(mockRows, 99, 5)
      expect(page).toBe(2)
      expect(pageRows).toHaveLength(1)
    })
  })
})
