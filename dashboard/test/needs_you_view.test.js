import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  paginate,
  sortRows,
  readSort,
  writeSort,
  resolveProjectFor,
  priorityPill,
  kindLabel
} from '../src/lib/needs_you_view.js'

// Mock localStorage for Node test environment
const localStorageMock = (() => {
  let store = {}
  return {
    getItem: (key) => store[key] || null,
    setItem: (key, value) => { store[key] = String(value) },
    removeItem: (key) => { delete store[key] },
    clear: () => { store = {} }
  }
})()

global.localStorage = localStorageMock

const row = (over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: 1,
  title: 'Test ticket',
  url: 'https://github.com/G-Eskayo/marvin/issues/1',
  kind: 'ready-for-human',
  unblocks: { count: 0, items: [] },
  ask: 'needs human input',
  priority: 'p0',
  ageDays: 5,
  ...over
})

describe('paginate', () => {
  it('test 6: paginates rows with default page size 10', () => {
    const rows = Array.from({ length: 25 }, (_, i) => row({ number: i + 1 }))
    const result = paginate(rows, { page: 1, pageSize: 10 })
    expect(result.rows).toHaveLength(10)
    expect(result.rows[0].number).toBe(1)
    expect(result.rows[9].number).toBe(10)
    expect(result.totalPages).toBe(3)
    expect(result.total).toBe(25)
  })

  it('test 7: returns correct page when page > 1', () => {
    const rows = Array.from({ length: 25 }, (_, i) => row({ number: i + 1 }))
    const result = paginate(rows, { page: 2, pageSize: 10 })
    expect(result.rows).toHaveLength(10)
    expect(result.rows[0].number).toBe(11)
    expect(result.currentPage).toBe(2)
  })

  it('test 8: handles last page with fewer items', () => {
    const rows = Array.from({ length: 25 }, (_, i) => row({ number: i + 1 }))
    const result = paginate(rows, { page: 3, pageSize: 10 })
    expect(result.rows).toHaveLength(5)
    expect(result.rows[0].number).toBe(21)
  })

  it('test 9: clamps out-of-range page to last valid page', () => {
    const rows = Array.from({ length: 5 }, (_, i) => row({ number: i + 1 }))
    const result = paginate(rows, { page: 10, pageSize: 10 })
    expect(result.rows).toEqual(rows)
    expect(result.currentPage).toBe(1)
    expect(result.totalPages).toBe(1)
  })

  it('test 10: defaults to page 1 when not specified', () => {
    const rows = Array.from({ length: 5 }, (_, i) => row({ number: i + 1 }))
    const result = paginate(rows)
    expect(result.rows[0].number).toBe(1)
    expect(result.currentPage).toBe(1)
  })
})

describe('sortRows', () => {
  it('test 11: sorts by unblocks descending', () => {
    const rows = [
      row({ number: 1, unblocks: { count: 2, items: [] } }),
      row({ number: 2, unblocks: { count: 5, items: [] } }),
      row({ number: 3, unblocks: { count: 1, items: [] } })
    ]
    const result = sortRows(rows, 'unblocks')
    expect(result.map((r) => r.number)).toEqual([2, 1, 3])
  })

  it('test 12: sorts by priority ascending (p0 first)', () => {
    const rows = [
      row({ number: 1, priority: 'p2' }),
      row({ number: 2, priority: 'p0' }),
      row({ number: 3, priority: 'p1' })
    ]
    const result = sortRows(rows, 'priority')
    expect(result.map((r) => r.number)).toEqual([2, 3, 1])
  })

  it('test 13: sorts by age descending (oldest first)', () => {
    const rows = [
      row({ number: 1, ageDays: 2 }),
      row({ number: 2, ageDays: 10 }),
      row({ number: 3, ageDays: 5 })
    ]
    const result = sortRows(rows, 'age')
    expect(result.map((r) => r.number)).toEqual([2, 3, 1])
  })

  it('test 14: default sort matches service ranking (unblocks, priority, age)', () => {
    const rows = [
      row({ number: 1, unblocks: { count: 1, items: [] }, priority: 'p0', ageDays: 2 }),
      row({ number: 2, unblocks: { count: 5, items: [] }, priority: 'p2', ageDays: 1 }),
      row({ number: 3, unblocks: { count: 1, items: [] }, priority: 'p0', ageDays: 5 })
    ]
    const result = sortRows(rows)
    expect(result.map((r) => r.number)).toEqual([2, 3, 1])
  })

  it('test 15: sort by kind (needs-info first)', () => {
    const rows = [
      row({ number: 1, kind: 'ready-for-human' }),
      row({ number: 2, kind: 'needs-info' }),
      row({ number: 3, kind: 'ready-for-human' })
    ]
    const result = sortRows(rows, 'kind')
    expect(result[0].kind).toBe('needs-info')
  })
})

describe('readSort / writeSort', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('test 16: writeSort saves sort preference to localStorage', () => {
    writeSort('priority')
    const saved = localStorage.getItem('needs-you-sort')
    expect(saved).toBe('priority')
  })

  it('test 17: readSort retrieves saved sort preference', () => {
    localStorage.setItem('needs-you-sort', 'age')
    const result = readSort()
    expect(result).toBe('age')
  })

  it('test 18: readSort defaults to unblocks when not set', () => {
    const result = readSort()
    expect(result).toBe('unblocks')
  })

  it('test 19: readSort handles corrupted storage gracefully', () => {
    localStorage.setItem('needs-you-sort', 'invalid')
    const result = readSort()
    expect(['unblocks', 'priority', 'age', 'kind']).toContain(result)
  })

  it('test 20: valid sort values are unblocks, priority, age, kind', () => {
    const validValues = ['unblocks', 'priority', 'age', 'kind']
    validValues.forEach((val) => {
      writeSort(val)
      expect(readSort()).toBe(val)
    })
  })
})

describe('resolveProjectFor', () => {
  const projects = [
    { id: 'marvin', repo: 'G-Eskayo/marvin', name: 'MARVIN' },
    { id: 'finance-os', repo: 'G-Eskayo/finance-os', name: 'Finance OS' },
    { id: 'portfolio', repo: 'gileskayo/portfolio', name: 'Portfolio' }
  ]

  it('test 21: resolves projectId to project object', () => {
    const result = resolveProjectFor('marvin', projects)
    expect(result.id).toBe('marvin')
    expect(result.name).toBe('MARVIN')
  })

  it('test 22: returns projectId as fallback when project not found', () => {
    const result = resolveProjectFor('unknown', projects)
    expect(result.id).toBe('unknown')
  })

  it('test 23: uses case-sensitive matching on projectId', () => {
    const result = resolveProjectFor('Marvin', projects)
    expect(result.id).toBe('Marvin')
  })

  it('test 24: returns full project object when found', () => {
    const result = resolveProjectFor('finance-os', projects)
    expect(result).toMatchObject({ id: 'finance-os', name: 'Finance OS' })
  })
})

describe('priorityPill', () => {
  it('test 25: formats p0 as highest priority', () => {
    const result = priorityPill('p0')
    expect(result).toMatchObject({ label: 'p0', class: expect.stringContaining('red') })
  })

  it('test 26: formats p1 as high priority', () => {
    const result = priorityPill('p1')
    expect(result).toMatchObject({ label: 'p1', class: expect.stringContaining('orange') })
  })

  it('test 27: formats p2 as medium priority', () => {
    const result = priorityPill('p2')
    expect(result).toMatchObject({ label: 'p2', class: expect.stringContaining('yellow') })
  })

  it('test 28: formats p3 or higher as low priority', () => {
    const result = priorityPill('p3')
    expect(result).toMatchObject({ label: 'p3', class: 'bg-neutral-800 text-neutral-400' })
  })

  it('test 29: handles null priority', () => {
    const result = priorityPill(null)
    expect(result).toMatchObject({ label: 'none', class: 'bg-neutral-800 text-neutral-400' })
  })
})

describe('kindLabel', () => {
  it('test 30: labels ready-for-human kind', () => {
    const result = kindLabel('ready-for-human')
    expect(result).toMatchObject({ label: expect.stringContaining('human'), class: expect.any(String) })
  })

  it('test 31: labels needs-info kind', () => {
    const result = kindLabel('needs-info')
    expect(result).toMatchObject({ label: expect.stringContaining('info'), class: expect.any(String) })
  })

  it('test 32: handles unknown kind', () => {
    const result = kindLabel('unknown')
    expect(result).toMatchObject({ label: expect.any(String), class: expect.any(String) })
  })
})

