import { describe, it, expect } from 'vitest'
import { paginate, sortRows, priorityStyle, readSortPreference, writeSortPreference, bodyState, sanitizeRows } from '../src/lib/needs_you_view.js'

describe('paginate', () => {
  const rows = [
    { number: 1, title: 'T1' },
    { number: 2, title: 'T2' },
    { number: 3, title: 'T3' },
    { number: 4, title: 'T4' },
    { number: 5, title: 'T5' },
    { number: 6, title: 'T6' }
  ]

  it('returns the first page by default', () => {
    const result = paginate(rows, 0, 5)
    expect(result.items).toHaveLength(5)
    expect(result.items[0].number).toBe(1)
    expect(result.items[4].number).toBe(5)
  })

  it('returns the correct page for higher indices', () => {
    const result = paginate(rows, 1, 5)
    expect(result.items).toHaveLength(1)
    expect(result.items[0].number).toBe(6)
  })

  it('calculates total pages correctly', () => {
    const result = paginate(rows, 0, 2)
    expect(result.pages).toBe(3)
    expect(result.total).toBe(6)
  })

  it('returns empty array for out-of-bounds page', () => {
    const result = paginate(rows, 10, 5)
    expect(result.items).toHaveLength(0)
  })
})

describe('sortRows', () => {
  const rows = [
    { number: 1, title: 'T1', unblocks: { count: 2 }, priority: 'p2', ageDays: 5, repo: 'G-Eskayo/marvin' },
    { number: 2, title: 'T2', unblocks: { count: 5 }, priority: 'p0', ageDays: 10, repo: 'G-Eskayo/marvin' },
    { number: 3, title: 'T3', unblocks: { count: 2 }, priority: 'p1', ageDays: 3, repo: 'G-Eskayo/other' }
  ]

  it('sorts by unblocks descending by default', () => {
    const sorted = sortRows(rows, 'unblocks')
    expect(sorted[0].number).toBe(2) // 5 unblocks
    expect(sorted[1].number).toBe(1) // 2 unblocks
    expect(sorted[2].number).toBe(3) // 2 unblocks
  })

  it('sorts by priority ascending', () => {
    const sorted = sortRows(rows, 'priority')
    expect(sorted[0].priority).toBe('p0')
    expect(sorted[1].priority).toBe('p1')
    expect(sorted[2].priority).toBe('p2')
  })

  it('sorts by age descending (oldest first)', () => {
    const sorted = sortRows(rows, 'oldest')
    expect(sorted[0].number).toBe(2) // 10 days
    expect(sorted[1].number).toBe(1) // 5 days
    expect(sorted[2].number).toBe(3) // 3 days
  })

  it('sorts by project name', () => {
    const boards = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/other', name: 'Other' }
    ]
    const sorted = sortRows(rows, 'project', { boards })
    expect(sorted[0].repo).toBe('G-Eskayo/marvin')
    expect(sorted[2].repo).toBe('G-Eskayo/other')
  })
})

describe('priorityStyle', () => {
  it('returns red styling for p0', () => {
    const style = priorityStyle('p0', 'ready-for-human')
    expect(style.bg).toBe('bg-red-950')
    expect(style.text).toBe('text-red-300')
    expect(style.label).toBe('P0')
  })

  it('returns orange styling for p1', () => {
    const style = priorityStyle('p1', 'ready-for-human')
    expect(style.bg).toBe('bg-orange-950')
    expect(style.text).toBe('text-orange-300')
    expect(style.label).toBe('P1')
  })

  it('returns neutral styling for p2', () => {
    const style = priorityStyle('p2', 'ready-for-human')
    expect(style.bg).toBe('bg-neutral-900')
    expect(style.text).toBe('text-neutral-400')
    expect(style.label).toBe('P2')
  })

  it('returns neutral styling for p3 or no priority', () => {
    const style = priorityStyle('p3', 'ready-for-human')
    expect(style.bg).toBe('bg-neutral-900')
    expect(style.text).toBe('text-neutral-400')
  })

  it('returns "needs answer" label for needs-info kind without priority', () => {
    const style = priorityStyle(null, 'needs-info')
    expect(style.label).toBe('needs answer')
  })

  it('returns "needs you" label for ready-for-human kind without priority', () => {
    const style = priorityStyle(null, 'ready-for-human')
    expect(style.label).toBe('needs you')
  })
})

describe('sort preference storage', () => {
  let mockStorage = {}
  const storage = {
    getItem: (key) => mockStorage[key] ?? null,
    setItem: (key, value) => { mockStorage[key] = value }
  }

  it('writes and reads sort preference', () => {
    writeSortPreference(storage, 'priority')
    const pref = readSortPreference(storage)
    expect(pref).toBe('priority')
  })

  it('returns default sort when none is saved', () => {
    mockStorage = {}
    const pref = readSortPreference(storage)
    expect(pref).toBe('unblocks')
  })

  it('handles missing storage gracefully', () => {
    const pref = readSortPreference(undefined)
    expect(pref).toBe('unblocks')
  })

  it('validates saved sort preference and returns default if invalid', () => {
    mockStorage = {}
    writeSortPreference(storage, 'invalid')
    const pref = readSortPreference(storage)
    expect(pref).toBe('unblocks')
  })
})

describe('bodyState', () => {
  it('returns error when error is truthy', () => {
    expect(bodyState([{ number: 1 }], true)).toBe('error')
    expect(bodyState([], true)).toBe('error')
  })

  it('returns empty when no rows and no error', () => {
    expect(bodyState([], null)).toBe('empty')
    expect(bodyState([], false)).toBe('empty')
  })

  it('returns loaded when rows exist', () => {
    expect(bodyState([{ number: 1 }], null)).toBe('loaded')
    expect(bodyState([{ number: 1 }, { number: 2 }], false)).toBe('loaded')
  })
})

describe('sanitizeRows', () => {
  const validRow = {
    number: 1,
    title: 'Test',
    repo: 'G-Eskayo/test',
    unblocks: { count: 0, items: [] },
    kind: 'ready-for-human',
    priority: null,
    ageDays: 0,
    ask: null
  }

  it('returns empty array for non-array input', () => {
    expect(sanitizeRows(null)).toEqual([])
    expect(sanitizeRows(undefined)).toEqual([])
    expect(sanitizeRows('not an array')).toEqual([])
    expect(sanitizeRows({})).toEqual([])
  })

  it('filters out rows missing required fields', () => {
    const rows = [
      validRow,
      { ...validRow, number: undefined },
      { ...validRow, title: 123 },
      { ...validRow, repo: null },
      { ...validRow, unblocks: null },
      { ...validRow, kind: '' }
    ]
    const result = sanitizeRows(rows)
    expect(result).toHaveLength(1)
    expect(result[0].number).toBe(1)
  })

  it('caps array at 10000 rows', () => {
    const rows = Array.from({ length: 15000 }, (_, i) => ({ ...validRow, number: i }))
    const result = sanitizeRows(rows)
    expect(result).toHaveLength(10000)
    expect(result[9999].number).toBe(9999)
  })

  it('preserves valid rows with all required fields', () => {
    const rows = [
      validRow,
      { ...validRow, number: 2, title: 'Another', ask: 'What should we do?' }
    ]
    const result = sanitizeRows(rows)
    expect(result).toHaveLength(2)
    expect(result[1].ask).toBe('What should we do?')
  })
})
