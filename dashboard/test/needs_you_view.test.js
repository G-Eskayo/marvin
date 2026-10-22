import { describe, it, expect } from 'vitest'
import {
  sortRows, paginate, priorityPill, kindLabel, applyLoadResult, getSortOptions,
  readSortPreference, writeSortPreference
} from '../src/lib/needs_you_view.js'

const row = (over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: 1,
  title: 'Test',
  url: 'http://test',
  kind: 'ready-for-human',
  unblocks: { count: 0 },
  ask: 'test',
  priority: null,
  ageDays: 0,
  ...over
})

describe('needs_you_view', () => {
  it('sortRows by unblocks (default), defending against missing unblocks', () => {
    const rows = [
      row({ number: 1, unblocks: { count: 0 } }),
      row({ number: 2, unblocks: { count: 3 } }),
      row({ number: 3, unblocks: undefined })
    ]
    const sorted = sortRows(rows)
    expect(sorted.map(r => r.number)).toEqual([2, 1, 3])
  })

  it('sortRows by priority (high first, then age)', () => {
    const rows = [
      row({ number: 1, priority: 'p1', ageDays: 5 }),
      row({ number: 2, priority: 'p3', ageDays: 10 }),
      row({ number: 3, priority: 'p1', ageDays: 3 })
    ]
    const sorted = sortRows(rows, 'priority')
    expect(sorted.map(r => r.number)).toEqual([1, 3, 2])
  })

  it('sortRows by age (oldest first)', () => {
    const rows = [
      row({ number: 1, ageDays: 5 }),
      row({ number: 2, ageDays: 10 }),
      row({ number: 3, ageDays: 2 })
    ]
    const sorted = sortRows(rows, 'age')
    expect(sorted.map(r => r.number)).toEqual([2, 1, 3])
  })

  it('sortRows by project (with unblocks tie-breaker)', () => {
    const rows = [
      row({ number: 1, project: 'z-proj', unblocks: { count: 2 } }),
      row({ number: 2, project: 'a-proj', unblocks: { count: 1 } }),
      row({ number: 3, project: 'a-proj', unblocks: { count: 5 } })
    ]
    const sorted = sortRows(rows, 'project')
    expect(sorted.map(r => r.number)).toEqual([3, 2, 1])
  })

  it('paginate returns correct slice and metadata', () => {
    const rows = Array.from({ length: 12 }, (_, i) => row({ number: i + 1 }))
    const page1 = paginate(rows, 1, 5)
    expect(page1.rows).toHaveLength(5)
    expect(page1.rows[0].number).toBe(1)
    expect(page1.totalPages).toBe(3)

    const page2 = paginate(rows, 2, 5)
    expect(page2.rows[0].number).toBe(6)
  })

  it('priorityPill returns correct colors and text', () => {
    expect(priorityPill('p0')).toMatchObject({ text: 'P0', className: expect.stringContaining('red') })
    expect(priorityPill('p1')).toMatchObject({ text: 'P1', className: expect.stringContaining('orange') })
    expect(priorityPill('p2')).toMatchObject({ text: 'P2', className: expect.stringContaining('neutral') })
    expect(priorityPill('p3')).toMatchObject({ text: 'P3', className: expect.stringContaining('neutral') })
    expect(priorityPill(null)).toBe(null)
  })

  it('kindLabel returns lowercase text', () => {
    expect(kindLabel('needs-info')).toBe('needs answer')
    expect(kindLabel('ready-for-human')).toBe('needs you')
    expect(kindLabel(null)).toBe('needs you')
  })

  it('applyLoadResult returns loaded data (any array) or saved fallback', () => {
    const saved = [row({ number: 1 })]
    const loaded = [row({ number: 2 }), row({ number: 3 })]
    expect(applyLoadResult(saved, loaded)).toEqual(loaded)
    expect(applyLoadResult(saved, [])).toEqual([])
    expect(applyLoadResult(saved, null)).toEqual(saved)
    expect(applyLoadResult(saved, undefined)).toEqual(saved)
  })

  it('getSortOptions returns all options', () => {
    const opts = getSortOptions()
    expect(opts).toHaveLength(4)
    expect(opts.map(o => o.id)).toContain('unblocks')
    expect(opts.map(o => o.id)).toContain('project')
  })

  it('readSortPreference from storage or defaults', () => {
    const storage = {
      getItem: (k) => k === 'needsYou.sort' ? 'age' : null
    }
    expect(readSortPreference(storage)).toBe('age')
    expect(readSortPreference({ getItem: () => null })).toBe('unblocks')
    expect(readSortPreference({ getItem: () => 'invalid' })).toBe('unblocks')
  })

  it('writeSortPreference to storage', () => {
    const items = {}
    const storage = {
      getItem: (k) => items[k],
      setItem: (k, v) => { items[k] = v }
    }
    writeSortPreference(storage, 'priority')
    expect(readSortPreference(storage)).toBe('priority')
  })

  it('sortRows by priority treats malformed priority strings (NaN) as 99', () => {
    const rows = [
      row({ number: 1, priority: 'p1', ageDays: 5 }),
      row({ number: 2, priority: 'invalid', ageDays: 10 }),
      row({ number: 3, priority: null, ageDays: 3 })
    ]
    const sorted = sortRows(rows, 'priority')
    // p1 sorts first, then malformed and null both get 99, sorted by age
    expect(sorted.map(r => r.number)).toEqual([1, 2, 3])
  })

  it('paginate clamps currentPage to valid range', () => {
    const rows = Array.from({ length: 12 }, (_, i) => row({ number: i + 1 }))
    // Request page 100 (past the end)
    const result = paginate(rows, 100, 5)
    expect(result.currentPage).toBe(3)
    expect(result.rows[0].number).toBe(11)
    // Request page 0 (before the start)
    const result2 = paginate(rows, 0, 5)
    expect(result2.currentPage).toBe(1)
    expect(result2.rows[0].number).toBe(1)
  })
})
