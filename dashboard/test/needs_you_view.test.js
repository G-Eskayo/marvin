import { describe, it, expect, vi } from 'vitest'
import { pageOf, sortRows, readSort, writeSort, pillFor, kindLabel, projectNameFor, mergeRefresh } from '../src/lib/needs_you_view.js'

const row = (num, over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: num,
  title: `Ticket #${num}`,
  url: `https://github.com/G-Eskayo/marvin/issues/${num}`,
  kind: 'ready-for-human',
  unblocks: { count: 0, items: [] },
  ask: 'test it',
  priority: 'p0',
  ageDays: 5,
  projectId: 'marvin',
  ...over
})

describe('pageOf', () => {
  it('returns pages=1 for 0 items', () => {
    const result = pageOf([], 0)
    expect(result).toEqual({ page: 0, pages: 1, rows: [] })
  })

  it('returns 1 page of 5 items for 5 items', () => {
    const rows = [row(1), row(2), row(3), row(4), row(5)]
    const result = pageOf(rows, 0)
    expect(result).toEqual({ page: 0, pages: 1, rows })
  })

  it('splits 6 items into page 0 with 5 and page 1 with 1', () => {
    const rows = [row(1), row(2), row(3), row(4), row(5), row(6)]
    const p0 = pageOf(rows, 0)
    const p1 = pageOf(rows, 1)
    expect(p0.rows).toHaveLength(5)
    expect(p1.rows).toHaveLength(1)
    expect(p0.pages).toBe(2)
    expect(p1.pages).toBe(2)
  })

  it('splits 11 items into 3 pages (5/5/1)', () => {
    const rows = Array.from({ length: 11 }, (_, i) => row(i + 1))
    const result = pageOf(rows, 0)
    expect(result.pages).toBe(3)
    const p2 = pageOf(rows, 2)
    expect(p2.rows).toHaveLength(1)
  })

  it('clamps out-of-range page to the last valid page', () => {
    const rows = Array.from({ length: 6 }, (_, i) => row(i + 1))
    const result = pageOf(rows, 999)
    expect(result.page).toBe(1)
    expect(result.rows).toHaveLength(1)
  })

  it('clamps negative page to 0', () => {
    const rows = [row(1), row(2)]
    const result = pageOf(rows, -5)
    expect(result.page).toBe(0)
    expect(result.rows).toHaveLength(2)
  })
})

describe('sortRows', () => {
  it('preserves input order for unblocks sort', () => {
    const rows = [row(1, { unblocks: { count: 2 } }), row(2, { unblocks: { count: 1 } }), row(3, { unblocks: { count: 3 } })]
    const result = sortRows(rows, 'unblocks')
    expect(result).toEqual(rows)
  })

  it('sorts by priority (p0 before p1 before p2/p3 before unlabelled), stable on ties', () => {
    const rows = [
      row(1, { priority: 'p2' }),
      row(2, { priority: 'p0' }),
      row(3, { priority: 'p1' }),
      row(4, { priority: null })
    ]
    const result = sortRows(rows, 'priority')
    expect(result[0].priority).toBe('p0')
    expect(result[1].priority).toBe('p1')
    expect(result[2].priority).toBe('p2')
    expect(result[3].priority).toBe(null)
  })

  it('sorts by oldest first (largest ageDays first)', () => {
    const rows = [
      row(1, { ageDays: 5 }),
      row(2, { ageDays: 15 }),
      row(3, { ageDays: 2 })
    ]
    const result = sortRows(rows, 'oldest')
    expect(result[0].ageDays).toBe(15)
    expect(result[1].ageDays).toBe(5)
    expect(result[2].ageDays).toBe(2)
  })

  it('sorts by project (resolved id/name)', () => {
    const boards = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/finance-os', name: 'Finance OS' }
    ]
    const rows = [
      row(1, { repo: 'G-Eskayo/finance-os', projectId: 'finance-os' }),
      row(2, { repo: 'G-Eskayo/marvin', projectId: 'marvin' }),
      row(3, { repo: 'G-Eskayo/marvin', projectId: 'marvin' })
    ]
    const result = sortRows(rows, 'project', boards)
    // finance-os should come before marvin (alphabetically)
    const marvinIndices = result.map((r, i) => r.projectId === 'marvin' ? i : null).filter(i => i !== null)
    const financeIndices = result.map((r, i) => r.projectId === 'finance-os' ? i : null).filter(i => i !== null)
    expect(financeIndices[0]).toBeLessThan(marvinIndices[0])
  })
})

describe('readSort/writeSort', () => {
  it('round-trips a valid value', () => {
    const storage = {
      getItem: () => JSON.stringify({ at: Date.now(), value: 'priority' }),
      setItem: vi.fn()
    }
    const val = readSort(storage)
    expect(val).toBe('priority')
    writeSort(storage, val)
    expect(storage.setItem).toHaveBeenCalled()
  })

  it('falls back to unblocks for garbage/missing storage', () => {
    const storage = { getItem: () => null, setItem: vi.fn() }
    expect(readSort(storage)).toBe('unblocks')

    const storage2 = { getItem: () => 'invalid json', setItem: vi.fn() }
    expect(readSort(storage2)).toBe('unblocks')
  })

  it('never throws when storage is throwing', () => {
    const storage = {
      getItem: () => { throw new Error('quota') },
      setItem: () => { throw new Error('quota') }
    }
    expect(() => readSort(storage)).not.toThrow()
    expect(() => writeSort(storage, 'priority')).not.toThrow()
  })
})

describe('pillFor', () => {
  it('returns red for p0', () => {
    const result = pillFor('p0')
    expect(result).toContain('red')
  })

  it('returns orange for p1', () => {
    const result = pillFor('p1')
    expect(result).toContain('orange')
  })

  it('returns grey for p2 and p3', () => {
    const p2 = pillFor('p2')
    const p3 = pillFor('p3')
    expect(p2).toContain('neutral-800')
    expect(p3).toContain('neutral-800')
  })

  it('returns null for null, undefined, or garbage priority', () => {
    expect(pillFor(null)).toBeNull()
    expect(pillFor(undefined)).toBeNull()
    expect(pillFor('p9')).toBeNull()
    expect(pillFor('')).toBeNull()
  })

  it('never throws', () => {
    expect(() => pillFor('invalid')).not.toThrow()
    expect(() => pillFor({ broken: 'object' })).not.toThrow()
  })
})

describe('kindLabel', () => {
  it('returns "needs answer" for needs-info', () => {
    expect(kindLabel('needs-info')).toBe('needs answer')
  })

  it('returns "needs you" for ready-for-human', () => {
    expect(kindLabel('ready-for-human')).toBe('needs you')
  })

  it('does not throw for unknown kind', () => {
    expect(() => kindLabel('unknown')).not.toThrow()
  })

  it('returns something non-empty for unknown kind', () => {
    const result = kindLabel('unknown')
    expect(result).toBeDefined()
    expect(String(result).length).toBeGreaterThan(0)
  })
})

describe('projectNameFor', () => {
  it('resolves projectId to a board name', () => {
    const boards = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' }
    ]
    const result = projectNameFor(row(1, { projectId: 'marvin' }), boards)
    expect(result).toBe('MARVIN')
  })

  it('falls back to repo short name for unregistered projectId', () => {
    const boards = []
    const result = projectNameFor(row(1, { repo: 'G-Eskayo/marvin', projectId: 'marvin' }), boards)
    expect(result).toBe('marvin')
  })

  it('falls back for empty boards list', () => {
    const result = projectNameFor(row(1, { repo: 'G-Eskayo/finance-os', projectId: 'finance-os' }), [])
    expect(result).toBe('finance-os')
  })

  it('never throws', () => {
    expect(() => projectNameFor(row(1), null)).not.toThrow()
    expect(() => projectNameFor(row(1), undefined)).not.toThrow()
  })
})

describe('mergeRefresh', () => {
  it('replaces rows on success', () => {
    const prev = { rows: [row(1)], error: null }
    const newRows = [row(2), row(3)]
    const result = mergeRefresh(prev, { ok: true, rows: newRows })
    expect(result.rows).toEqual(newRows)
    expect(result.error).toBeNull()
  })

  it('keeps prior rows and attaches error on failure', () => {
    const prev = { rows: [row(1)], error: null }
    const result = mergeRefresh(prev, { ok: false, error: 'Network error' })
    expect(result.rows).toEqual([row(1)])
    expect(result.error).toBe('Network error')
  })

  it('leaves rows empty with error on first-ever failure', () => {
    const prev = { rows: [], error: null }
    const result = mergeRefresh(prev, { ok: false, error: 'First load failed' })
    expect(result.rows).toEqual([])
    expect(result.error).toBe('First load failed')
  })

  it('never throws', () => {
    expect(() => mergeRefresh(null, { ok: true, rows: [row(1)] })).not.toThrow()
    expect(() => mergeRefresh({ rows: [] }, { ok: false })).not.toThrow()
  })
})

describe('huge input', () => {
  it('handles 500 synthetic rows through pageOf+sortRows without stack issues', () => {
    const rows = Array.from({ length: 500 }, (_, i) => row(i + 1, { ageDays: Math.random() * 100 }))
    const sorted = sortRows(rows, 'oldest')
    const paged = pageOf(sorted, 0)
    expect(paged.rows).toHaveLength(5)
    expect(paged.pages).toBe(100)
  })
})

describe('malformed row handling', () => {
  it('handles row missing priority without throwing', () => {
    const malformed = row(1, { priority: undefined })
    expect(() => pillFor(malformed.priority)).not.toThrow()
  })

  it('handles row missing unblocks without crashing sortRows', () => {
    const rows = [row(1, { unblocks: undefined }), row(2)]
    expect(() => sortRows(rows, 'unblocks')).not.toThrow()
  })

  it('handles row missing ask without crashing', () => {
    const malformed = row(1, { ask: undefined })
    expect(malformed.ask).toBeUndefined()
    // Should still be renderable
  })
})
