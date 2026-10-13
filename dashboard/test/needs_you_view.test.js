import { describe, it, expect } from 'vitest'
import { sortRows, paginate, kindLabel, priorityPill, loadSort, saveSort, loadCachedRows, saveCachedRows } from '../src/lib/needs_you_view.js'

const mockStorage = () => {
  const data = {}
  return {
    getItem: (key) => data[key] || null,
    setItem: (key, value) => { data[key] = value }
  }
}

const mockRow = (num, over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: num,
  title: `Ticket ${num}`,
  project: 'marvin',
  kind: 'ready-for-human',
  ask: `Task ${num}`,
  priority: null,
  ageDays: num,
  unblocks: { count: 0, items: [] },
  ...over
})

describe('sortRows', () => {
  it('sorts by priority ascending (p0 first)', () => {
    const rows = [
      mockRow(1, { priority: 'p2' }),
      mockRow(2, { priority: 'p0' }),
      mockRow(3, { priority: 'p1' })
    ]
    const sorted = sortRows(rows, 'priority', 'asc')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(3)
    expect(sorted[2].number).toBe(1)
  })

  it('sorts by priority descending', () => {
    const rows = [
      mockRow(1, { priority: 'p0' }),
      mockRow(2, { priority: 'p2' })
    ]
    const sorted = sortRows(rows, 'priority', 'desc')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(1)
  })

  it('sorts by age ascending', () => {
    const rows = [
      mockRow(1, { ageDays: 10 }),
      mockRow(2, { ageDays: 5 }),
      mockRow(3, { ageDays: 15 })
    ]
    const sorted = sortRows(rows, 'age', 'asc')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(1)
    expect(sorted[2].number).toBe(3)
  })

  it('sorts by age descending', () => {
    const rows = [
      mockRow(1, { ageDays: 10 }),
      mockRow(2, { ageDays: 5 })
    ]
    const sorted = sortRows(rows, 'age', 'desc')
    expect(sorted[0].number).toBe(1)
    expect(sorted[1].number).toBe(2)
  })

  it('sorts by unblocks count', () => {
    const rows = [
      mockRow(1, { unblocks: { count: 2 } }),
      mockRow(2, { unblocks: { count: 5 } }),
      mockRow(3, { unblocks: { count: 1 } })
    ]
    const sorted = sortRows(rows, 'unblocks', 'desc')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(1)
    expect(sorted[2].number).toBe(3)
  })

  it('does not mutate original array', () => {
    const rows = [mockRow(1), mockRow(2), mockRow(3)]
    const original = [...rows]
    sortRows(rows, 'age', 'asc')
    expect(rows).toEqual(original)
  })

  it('handles rows without priority', () => {
    const rows = [
      mockRow(1, { priority: null }),
      mockRow(2, { priority: 'p0' })
    ]
    const sorted = sortRows(rows, 'priority', 'asc')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(1)
  })
})

describe('paginate', () => {
  it('returns first page of 5 items (test 11)', () => {
    const rows = Array.from({ length: 12 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, 0)
    expect(result.items).toHaveLength(5)
    expect(result.items[0].number).toBe(1)
    expect(result.items[4].number).toBe(5)
    expect(result.hasNext).toBe(true)
    expect(result.hasPrev).toBe(false)
  })

  it('returns second page (test 12)', () => {
    const rows = Array.from({ length: 12 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, 1)
    expect(result.items).toHaveLength(5)
    expect(result.items[0].number).toBe(6)
    expect(result.hasNext).toBe(true)
    expect(result.hasPrev).toBe(true)
  })

  it('returns last page with fewer items (test 13)', () => {
    const rows = Array.from({ length: 12 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, 2)
    expect(result.items).toHaveLength(2)
    expect(result.items[0].number).toBe(11)
    expect(result.hasNext).toBe(false)
    expect(result.hasPrev).toBe(true)
  })

  it('clamps to max page for out of range (test 14)', () => {
    const rows = Array.from({ length: 5 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, 10)
    expect(result.items).toHaveLength(5)
    expect(result.pageNum).toBe(0)
  })

  it('includes pagination metadata (test 15)', () => {
    const rows = Array.from({ length: 12 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, 1)
    expect(result.total).toBe(12)
    expect(result.pageNum).toBe(1)
    expect(result.pageSize).toBe(5)
  })

  it('handles non-integer pageNum by flooring (test 16)', () => {
    const rows = Array.from({ length: 12 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, 1.7)
    expect(result.pageNum).toBe(1)
    expect(result.items[0].number).toBe(6)
  })

  it('handles NaN pageNum gracefully (test 17)', () => {
    const rows = Array.from({ length: 12 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, NaN)
    expect(result.pageNum).toBe(0)
    expect(result.items[0].number).toBe(1)
  })

  it('handles empty rows (test 18)', () => {
    const result = paginate([], 5, 0)
    expect(result.items).toEqual([])
    expect(result.total).toBe(0)
    expect(result.pageNum).toBe(0)
  })

  it('handles negative pageNum (test 19)', () => {
    const rows = Array.from({ length: 5 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 5, -1)
    expect(result.pageNum).toBe(0)
    expect(result.items[0].number).toBe(1)
  })

  it('handles page size of 0 by defaulting to 5 (test 20)', () => {
    const rows = Array.from({ length: 20 }, (_, i) => mockRow(i + 1))
    const result = paginate(rows, 0, 0)
    expect(result.pageSize).toBe(5)
    expect(result.items).toHaveLength(5)
  })
})

describe('kindLabel', () => {
  it('returns "needs answer" for needs-info kind (test 21)', () => {
    expect(kindLabel('needs-info')).toBe('needs answer')
  })

  it('returns "needs you" for ready-for-human kind (test 22)', () => {
    expect(kindLabel('ready-for-human')).toBe('needs you')
  })

  it('returns empty string for null/undefined (test 23)', () => {
    expect(kindLabel(null)).toBe('')
    expect(kindLabel(undefined)).toBe('')
  })

  it('returns unknown kinds as-is (test 24)', () => {
    expect(kindLabel('unknown-kind')).toBe('unknown-kind')
  })
})

describe('priorityPill', () => {
  it('returns P0 with red color (test 25)', () => {
    const pill = priorityPill('p0')
    expect(pill).toEqual({ label: 'P0', colorClass: 'bg-red-950/50 text-red-300' })
  })

  it('returns P1 with orange color (test 26)', () => {
    const pill = priorityPill('p1')
    expect(pill).toEqual({ label: 'P1', colorClass: 'bg-orange-950/50 text-orange-300' })
  })

  it('returns P2 with grey color (test 27)', () => {
    const pill = priorityPill('p2')
    expect(pill).toEqual({ label: 'P2', colorClass: 'bg-neutral-950/50 text-neutral-300' })
  })

  it('returns P3 with grey color (test 28)', () => {
    const pill = priorityPill('p3')
    expect(pill).toEqual({ label: 'P3', colorClass: 'bg-neutral-950/50 text-neutral-300' })
  })

  it('returns grey pill for null/undefined (test 29)', () => {
    const nullPill = priorityPill(null)
    const undefPill = priorityPill(undefined)
    expect(nullPill).toEqual({ label: 'P?', colorClass: 'bg-neutral-950/50 text-neutral-300' })
    expect(undefPill).toEqual({ label: 'P?', colorClass: 'bg-neutral-950/50 text-neutral-300' })
  })
})

describe('loadCachedRows / saveCachedRows', () => {
  it('saves and loads rows with {rows, at} shape (test 30)', () => {
    const storage = mockStorage()
    const rows = [mockRow(1), mockRow(2)]
    saveCachedRows(rows, storage)
    const loaded = loadCachedRows(storage)
    expect(loaded).not.toBeNull()
    expect(loaded.rows).toEqual(rows)
    expect(typeof loaded.at).toBe('number')
  })

  it('returns null when cache is empty (test 31)', () => {
    const storage = mockStorage()
    expect(loadCachedRows(storage)).toBeNull()
  })

  it('returns null for old array format (test 32)', () => {
    const storage = mockStorage()
    storage.setItem('needs-you:rows', JSON.stringify([mockRow(1)]))
    expect(loadCachedRows(storage)).toBeNull()
  })

  it('returns null for malformed JSON (test 33)', () => {
    const storage = mockStorage()
    storage.setItem('needs-you:rows', '{invalid json')
    expect(loadCachedRows(storage)).toBeNull()
  })

  it('silently fails on storage errors (test 34)', () => {
    const badStorage = {
      getItem: () => { throw new Error('quota exceeded') },
      setItem: () => { throw new Error('quota exceeded') }
    }
    expect(() => loadCachedRows(badStorage)).not.toThrow()
    expect(loadCachedRows(badStorage)).toBeNull()
  })
})

describe('loadSort / saveSort', () => {
  it('loads default sort when storage is null', () => {
    const sort = loadSort(null)
    expect(sort).toEqual({ field: 'unblocks', direction: 'desc' })
  })

  it('saves and loads sort preference', () => {
    const storage = mockStorage()
    saveSort('age', 'desc', storage)
    const loaded = loadSort(storage)
    expect(loaded).toEqual({ field: 'age', direction: 'desc' })
  })

  it('handles malformed stored sort gracefully', () => {
    const badStorage = {
      getItem: () => 'invalid json',
      setItem: () => {}
    }
    const sort = loadSort(badStorage)
    expect(sort).toEqual({ field: 'unblocks', direction: 'desc' })
  })
})
