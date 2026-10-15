import { describe, it, expect, vi, beforeEach } from 'vitest'
import { paginate, sortRows, readSort, writeSort, resolveProjectFor } from '../src/lib/needs_you_view.js'
import { readSaved, writeSaved } from '../src/lib/saved_state.js'

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

const mockRow = (over = {}) => ({
  repo: 'G-Eskayo/marvin',
  projectId: 'marvin',
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

const mockProjects = [
  { id: 'marvin', name: 'MARVIN', repo: 'G-Eskayo/marvin' },
  { id: 'finance-os', name: 'Finance OS', repo: 'G-Eskayo/finance-os' }
]

describe('NeedsYouList integration', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('test 36: paginate with saved state works correctly', () => {
    const rows = Array.from({ length: 25 }, (_, i) => mockRow({ number: i + 1 }))
    const saved = { at: Date.now(), value: rows }
    writeSaved(localStorage, 'test-key', rows)
    const loaded = readSaved(localStorage, 'test-key')
    expect(loaded).not.toBeNull()
    expect(loaded.value).toHaveLength(25)

    const paginated = paginate(loaded.value, { page: 1, pageSize: 10 })
    expect(paginated.rows).toHaveLength(10)
    expect(paginated.totalPages).toBe(3)
  })

  it('test 37: paginate clamps out-of-range page to valid range', () => {
    const rows = Array.from({ length: 15 }, (_, i) => mockRow({ number: i + 1 }))
    const result = paginate(rows, { page: 100, pageSize: 10 })
    expect(result.currentPage).toBe(2)
    expect(result.rows.length).toBeLessThanOrEqual(10)
  })

  it('test 38: paginate handles empty rows with clamped page', () => {
    const result = paginate([], { page: 10, pageSize: 10 })
    expect(result.currentPage).toBe(1)
    expect(result.totalPages).toBe(0)
    expect(result.rows).toEqual([])
  })

  it('test 39: sortRows sorts by unblocks descending', () => {
    const rows = [
      mockRow({ number: 1, unblocks: { count: 1, items: [] } }),
      mockRow({ number: 2, unblocks: { count: 5, items: [] } }),
      mockRow({ number: 3, unblocks: { count: 2, items: [] } })
    ]
    const sorted = sortRows(rows, 'unblocks')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(3)
    expect(sorted[2].number).toBe(1)
  })

  it('test 40: resolveProjectFor uses projectId and projects list', () => {
    const result = resolveProjectFor('marvin', mockProjects)
    expect(result.id).toBe('marvin')
    expect(result.name).toBe('MARVIN')

    const missing = resolveProjectFor('unknown', mockProjects)
    expect(missing.id).toBe('unknown')
  })

  it('test 41: writeSort and readSort handle errors gracefully', () => {
    localStorage.setItem('needs-you-sort', 'unblocks')
    expect(readSort()).toBe('unblocks')

    writeSort('priority')
    expect(readSort()).toBe('priority')

    writeSort('invalid')
    expect(readSort()).toBe('priority')

    localStorage.clear()
    expect(readSort()).toBe('unblocks')
  })
})
