import { describe, it, expect, beforeEach } from 'vitest'
import {
  sortRows, paginate, priorityPill, kindLabel, readCache, writeCache,
  readSort, writeSort, applyFetch
} from '../src/lib/needs_you_view.js'

const mockRow = (n, over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: n,
  title: `Row ${n}`,
  url: `https://example.com/${n}`,
  kind: 'ready-for-human',
  unblocks: { count: 0, items: [] },
  ask: 'test',
  priority: null,
  ageDays: 1,
  project: 'marvin',
  ...over
})

describe('sortRows', () => {
  // Test 1: sort by priority
  it('sorts by priority ascending (p0 first)', () => {
    const rows = [
      mockRow(1, { priority: 'p2' }),
      mockRow(2, { priority: 'p0' }),
      mockRow(3, { priority: null })
    ]
    const sorted = sortRows(rows, 'priority')
    expect(sorted[0].priority).toBe('p0')
    expect(sorted[1].priority).toBe('p2')
    expect(sorted[2].priority).toBeNull()
  })

  // Test 2: sort by unblocks descending
  it('sorts by unblocks count descending', () => {
    const rows = [
      mockRow(1, { unblocks: { count: 2, items: [] } }),
      mockRow(2, { unblocks: { count: 5, items: [] } }),
      mockRow(3, { unblocks: { count: 0, items: [] } })
    ]
    const sorted = sortRows(rows, 'unblocks')
    expect(sorted[0].unblocks.count).toBe(5)
    expect(sorted[1].unblocks.count).toBe(2)
    expect(sorted[2].unblocks.count).toBe(0)
  })

  // Test 3: sort by age descending
  it('sorts by age descending (oldest first)', () => {
    const rows = [
      mockRow(1, { ageDays: 2 }),
      mockRow(2, { ageDays: 10 }),
      mockRow(3, { ageDays: 1 })
    ]
    const sorted = sortRows(rows, 'age')
    expect(sorted[0].ageDays).toBe(10)
    expect(sorted[1].ageDays).toBe(2)
    expect(sorted[2].ageDays).toBe(1)
  })

  // Test 4: sort by project
  it('sorts by project alphabetically', () => {
    const rows = [
      mockRow(1, { project: 'zebra' }),
      mockRow(2, { project: 'apple' }),
      mockRow(3, { project: 'marvin' })
    ]
    const sorted = sortRows(rows, 'project')
    expect(sorted[0].project).toBe('apple')
    expect(sorted[1].project).toBe('marvin')
    expect(sorted[2].project).toBe('zebra')
  })
})

describe('paginate', () => {
  // Test 5: basic pagination
  it('returns correct page of items', () => {
    const rows = [mockRow(1), mockRow(2), mockRow(3), mockRow(4), mockRow(5)]
    const result = paginate(rows, 1, 2)
    expect(result.items).toHaveLength(2)
    expect(result.items[0].number).toBe(1)
    expect(result.items[1].number).toBe(2)
  })

  // Test 6: page boundary
  it('handles last page with fewer items', () => {
    const rows = [mockRow(1), mockRow(2), mockRow(3)]
    const result = paginate(rows, 2, 2)
    expect(result.items).toHaveLength(1)
    expect(result.items[0].number).toBe(3)
  })

  // Test 7: total pages and count
  it('calculates totalPages and totalCount correctly', () => {
    const rows = [mockRow(1), mockRow(2), mockRow(3), mockRow(4), mockRow(5)]
    const result = paginate(rows, 1, 2)
    expect(result.totalPages).toBe(3)
    expect(result.totalCount).toBe(5)
    expect(result.currentPage).toBe(1)
  })

  // Test 8: empty rows
  it('handles empty rows', () => {
    const result = paginate([], 1, 10)
    expect(result.items).toHaveLength(0)
    expect(result.totalPages).toBe(1)
    expect(result.totalCount).toBe(0)
  })

  // Test 8b: clamps page to valid range
  it('clamps page to valid range', () => {
    const rows = [mockRow(1), mockRow(2), mockRow(3)]
    const result1 = paginate(rows, 0, 2)
    expect(result1.currentPage).toBe(1)
    const result2 = paginate(rows, 99, 2)
    expect(result2.currentPage).toBe(2)
  })
})

describe('priorityPill', () => {
  // Test 9: priority display text with CSS
  it('returns correct display text and CSS for priority levels', () => {
    const p0 = priorityPill('p0')
    expect(p0.text).toBe('Critical')
    expect(p0.className).toContain('red')
    const p1 = priorityPill('p1')
    expect(p1.text).toBe('High')
    expect(p1.className).toContain('orange')
    const p2 = priorityPill('p2')
    expect(p2.text).toBe('Medium')
    expect(p2.className).toContain('yellow')
    const p3 = priorityPill('p3')
    expect(p3.text).toBe('Low')
  })

  // Test 10: null priority
  it('returns null for no priority', () => {
    expect(priorityPill(null)).toBeNull()
    expect(priorityPill(undefined)).toBeNull()
  })

  // Test 11: unknown priority
  it('returns default CSS for unknown priority', () => {
    const custom = priorityPill('custom')
    expect(custom.text).toBe('custom')
    expect(custom.className).toBeDefined()
  })
})

describe('kindLabel', () => {
  // Test 12: kind display text
  it('returns correct display text for kinds', () => {
    expect(kindLabel('needs-info')).toBe('Needs info')
    expect(kindLabel('ready-for-human')).toBe('Ready for you')
  })

  // Test 13: unknown kind
  it('returns the input for unknown kind', () => {
    expect(kindLabel('other')).toBe('other')
  })
})

describe('cache storage', () => {
  // Test 14: read and write cache
  it('writes and reads cache from storage', () => {
    const storage = { data: {}, getItem: function(k) { return this.data[k] || null }, setItem: function(k, v) { this.data[k] = v } }
    const rows = [mockRow(1), mockRow(2)]
    writeCache(storage, rows)
    const cached = readCache(storage)
    expect(cached).toEqual(rows)
  })

  // Test 15: read/write sort
  it('writes and reads sort key from storage', () => {
    const storage = { data: {}, getItem: function(k) { return this.data[k] || null }, setItem: function(k, v) { this.data[k] = v } }
    writeSort(storage, 'priority')
    expect(readSort(storage)).toBe('priority')
  })

  // Test 16: null storage gracefully
  it('handles null storage without crashing', () => {
    expect(readCache(null)).toBeNull()
    expect(() => writeCache(null, [])).not.toThrow()
    expect(readSort(null)).toBe('default')
    expect(() => writeSort(null, 'priority')).not.toThrow()
  })
})

describe('applyFetch reducer', () => {
  const initialState = { loading: false, error: null, rows: [], sortKey: 'default', page: 1 }

  // Test 17 (implicit): FETCH_START sets loading
  it('sets loading=true and clears error on FETCH_START', () => {
    const result = applyFetch(initialState, { type: 'FETCH_START' })
    expect(result.loading).toBe(true)
    expect(result.error).toBeNull()
  })

  // Test 18 (implicit): FETCH_SUCCESS
  it('clears loading and error on FETCH_SUCCESS, stores rows and timestamp', () => {
    const rows = [mockRow(1)]
    const now = Date.now()
    const result = applyFetch(initialState, { type: 'FETCH_SUCCESS', payload: { rows, at: now } })
    expect(result.loading).toBe(false)
    expect(result.error).toBeNull()
    expect(result.rows).toEqual(rows)
    expect(result.lastFetch).toBe(now)
  })

  // Test 19 (implicit): FETCH_ERROR
  it('sets error on FETCH_ERROR', () => {
    const error = 'Network failed'
    const result = applyFetch(initialState, { type: 'FETCH_ERROR', payload: { error } })
    expect(result.loading).toBe(false)
    expect(result.error).toBe(error)
  })

  // Test 20 (implicit): SET_SORT
  it('updates sortKey on SET_SORT and resets page to 1', () => {
    const stateOnPage2 = { ...initialState, page: 2 }
    const result = applyFetch(stateOnPage2, { type: 'SET_SORT', payload: { key: 'priority' } })
    expect(result.sortKey).toBe('priority')
    expect(result.page).toBe(1)
  })

  // Test 21 (implicit): SET_PAGE
  it('updates page on SET_PAGE', () => {
    const result = applyFetch(initialState, { type: 'SET_PAGE', payload: { page: 2 } })
    expect(result.page).toBe(2)
  })

  // Test 22 (implicit): unknown action
  it('returns state unchanged for unknown action', () => {
    const result = applyFetch(initialState, { type: 'UNKNOWN' })
    expect(result).toEqual(initialState)
  })

  // Test 23 (implicit): requestId tracking
  it('tracks requestId on FETCH_START', () => {
    const result = applyFetch(initialState, { type: 'FETCH_START', payload: { requestId: 'req-123' } })
    expect(result.requestId).toBe('req-123')
  })

  it('preserves requestId on FETCH_SUCCESS', () => {
    const rows = [mockRow(1)]
    const now = Date.now()
    const result = applyFetch(initialState, { type: 'FETCH_SUCCESS', payload: { rows, at: now, requestId: 'req-123' } })
    expect(result.requestId).toBe('req-123')
  })
})
