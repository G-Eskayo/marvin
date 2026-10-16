import { describe, it, expect } from 'vitest'
import {
  SORTS,
  sortRows,
  resolveProject,
  paginate,
  pillStyle,
  kindLabel,
  readCache,
  writeCache,
  readSortPref,
  writeSortPref,
  shouldApply,
  initialViewState,
  applyFetchError,
  emptyStateText,
  freshnessText
} from '../src/lib/needs_you_view.js'

const row = (num, over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: num,
  title: `Ticket #${num}`,
  ask: 'test this',
  priority: null,
  ageDays: 0,
  kind: 'ready-for-human',
  unblocks: { count: 0, items: [] },
  ...over
})

describe('paginate', () => {
  it('handles 0 items', () => {
    const result = paginate([], 1)
    expect(result).toEqual({ page: 1, totalPages: 1, pageRows: [] })
  })

  it('handles 5 items on page 1', () => {
    const rows = [1, 2, 3, 4, 5].map(n => row(n))
    const result = paginate(rows, 1, 5)
    expect(result.totalPages).toBe(1)
    expect(result.pageRows.length).toBe(5)
  })

  it('handles 6 items across 2 pages', () => {
    const rows = [1, 2, 3, 4, 5, 6].map(n => row(n))
    const result = paginate(rows, 2, 5)
    expect(result.totalPages).toBe(2)
    expect(result.pageRows.length).toBe(1)
    expect(result.pageRows[0].number).toBe(6)
  })

  it('handles 11 items across 3 pages', () => {
    const rows = Array.from({ length: 11 }, (_, i) => row(i + 1))
    const result = paginate(rows, 3, 5)
    expect(result.totalPages).toBe(3)
    expect(result.pageRows.length).toBe(1)
  })

  it('clamps page beyond totalPages', () => {
    const rows = [1, 2].map(n => row(n))
    const result = paginate(rows, 99, 5)
    expect(result.page).toBe(1) // 2 items with pageSize 5 = 1 page total
    expect(result.pageRows.length).toBe(2)
  })

  it('clamps negative page to 1', () => {
    const rows = [1, 2].map(n => row(n))
    const result = paginate(rows, -5, 5)
    expect(result.page).toBe(1)
  })

  it('handles large input (250 rows)', () => {
    const rows = Array.from({ length: 250 }, (_, i) => row(i + 1))
    const result = paginate(rows, 50, 5)
    expect(result.totalPages).toBe(50)
    expect(result.pageRows.length).toBe(5)
  })
})

describe('sortRows', () => {
  it('unblocks sort: higher count first', () => {
    const rows = [
      row(1, { unblocks: { count: 1 } }),
      row(2, { unblocks: { count: 3 } }),
      row(3, { unblocks: { count: 2 } })
    ]
    const result = sortRows(rows, 'unblocks')
    expect(result[0].number).toBe(2)
    expect(result[1].number).toBe(3)
    expect(result[2].number).toBe(1)
  })

  it('priority sort: p0 before p1 before p2/p3 before null', () => {
    const rows = [
      row(1, { priority: null }),
      row(2, { priority: 'p0' }),
      row(3, { priority: 'p2' }),
      row(4, { priority: 'p1' })
    ]
    const result = sortRows(rows, 'priority')
    expect(result[0].priority).toBe('p0')
    expect(result[1].priority).toBe('p1')
    expect(result[2].priority).toBe('p2')
    expect(result[3].priority).toBe(null)
  })

  it('oldest sort: higher ageDays first', () => {
    const rows = [
      row(1, { ageDays: 5 }),
      row(2, { ageDays: 20 }),
      row(3, { ageDays: 10 })
    ]
    const result = sortRows(rows, 'oldest')
    expect(result[0].ageDays).toBe(20)
    expect(result[1].ageDays).toBe(10)
    expect(result[2].ageDays).toBe(5)
  })

  it('project sort: alphabetical by project name', () => {
    const rows = [
      row(1, { project: 'marvin' }),
      row(2, { project: 'finance-os' }),
      row(3, { project: 'killer-sudoku' })
    ]
    const boards = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/finance-os', name: 'Finance OS' },
      { repo: 'G-Eskayo/killer-sudoku', name: 'Killer Sudoku' }
    ]
    const result = sortRows(rows, 'project', boards)
    // Sort alphabetically: finance-os < killer-sudoku < marvin
    expect(result[0].project).toBe('finance-os')
  })

  it('project sort: board with no name falls back to id without crashing', () => {
    const rows = [
      row(1, { project: 'marvin' }),
      row(2, { project: 'finance-os' })
    ]
    const boards = [
      { repo: 'G-Eskayo/marvin', name: undefined }, // board has no name
      { repo: 'G-Eskayo/finance-os', name: 'Finance OS' }
    ]
    expect(() => sortRows(rows, 'project', boards)).not.toThrow()
    const result = sortRows(rows, 'project', boards)
    // Should still have sorted deterministically
    expect(result).toHaveLength(2)
  })

  it('unknown sort key falls back to unblocks', () => {
    const rows = [
      row(1, { unblocks: { count: 1 } }),
      row(2, { unblocks: { count: 3 } })
    ]
    const result = sortRows(rows, 'unknown-sort')
    expect(result[0].unblocks.count).toBe(3)
  })

  it('stable sort: ties maintain input order', () => {
    const rows = [
      row(1, { priority: 'p1', unblocks: { count: 0 }, ageDays: 5 }),
      row(2, { priority: 'p1', unblocks: { count: 0 }, ageDays: 5 }),
      row(3, { priority: 'p1', unblocks: { count: 0 }, ageDays: 5 })
    ]
    const result = sortRows(rows, 'priority')
    expect(result[0].number).toBe(1)
    expect(result[1].number).toBe(2)
    expect(result[2].number).toBe(3)
  })
})

describe('pillStyle', () => {
  it('p0 is red', () => {
    const style = pillStyle('p0')
    expect(style.container).toContain('bg-red-950')
    expect(style.text).toContain('text-red-300')
  })

  it('p1 is orange', () => {
    const style = pillStyle('p1')
    expect(style.container).toContain('bg-orange-950')
    expect(style.text).toContain('text-orange-300')
  })

  it('p2/p3/null is grey', () => {
    expect(pillStyle('p2').container).toContain('bg-neutral-800')
    expect(pillStyle('p3').container).toContain('bg-neutral-800')
    expect(pillStyle(null).container).toContain('bg-neutral-800')
  })
})

describe('kindLabel', () => {
  it('needs-info -> "needs answer"', () => {
    expect(kindLabel('needs-info')).toBe('needs answer')
  })

  it('ready-for-human -> "needs you"', () => {
    expect(kindLabel('ready-for-human')).toBe('needs you')
  })

  it('unknown kind has safe fallback', () => {
    const label = kindLabel('unknown-kind')
    expect(typeof label).toBe('string')
    expect(label.length > 0).toBe(true)
  })
})

describe('resolveProject', () => {
  it('project label matches board repo', () => {
    const row = { project: 'marvin', repo: 'G-Eskayo/marvin' }
    const boards = [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }]
    const result = resolveProject(row, boards)
    expect(result.id).toBe('marvin')
    expect(result.name).toBe('MARVIN')
  })

  it('project label is cross-repo', () => {
    const row = { project: 'killer-sudoku', repo: 'G-Eskayo/marvin' }
    const boards = [
      { repo: 'G-Eskayo/marvin', name: 'MARVIN' },
      { repo: 'G-Eskayo/killer-sudoku', name: 'Killer Sudoku' }
    ]
    const result = resolveProject(row, boards)
    expect(result.id).toBe('killer-sudoku')
    expect(result.name).toBe('Killer Sudoku')
  })

  it('unregistered project falls back to raw id', () => {
    const row = { project: 'unknown-project', repo: 'G-Eskayo/marvin' }
    const boards = [{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }]
    const result = resolveProject(row, boards)
    expect(result.id).toBe('unknown-project')
    expect(result.name).toBe('unknown-project')
  })

  it('null/empty boards list doesn\'t crash', () => {
    const row = { project: 'marvin', repo: 'G-Eskayo/marvin' }
    const result = resolveProject(row, null)
    expect(result.id).toBe('marvin')
  })

  it('duplicate board resolution is deterministic', () => {
    const row = { project: 'test', repo: 'G-Eskayo/test' }
    // Two boards with same projectIdOf result (shouldn't happen, but defensive)
    const boards = [
      { repo: 'G-Eskayo/test', name: 'Test 1' },
      { repo: 'O-Other/test', name: 'Test 2' }
    ]
    const result1 = resolveProject(row, boards)
    const result2 = resolveProject(row, boards)
    expect(result1).toEqual(result2)
  })
})

describe('storage: readCache / writeCache', () => {
  const mockStorage = () => {
    const data = {}
    return {
      getItem: (key) => data[key],
      setItem: (key, value) => { data[key] = value }
    }
  }

  it('readCache on empty storage returns empty', () => {
    const storage = mockStorage()
    const result = readCache(storage)
    expect(result).toEqual([])
  })

  it('writeCache then readCache round-trips', () => {
    const storage = mockStorage()
    const rows = [row(1), row(2)]
    writeCache(storage, rows)
    const result = readCache(storage)
    expect(result).toHaveLength(2)
    expect(result[0].number).toBe(1)
  })

  it('readCache on corrupted JSON falls back to empty', () => {
    const storage = mockStorage()
    storage.getItem = () => 'not json'
    const result = readCache(storage)
    expect(result).toEqual([])
  })

  it('readCache on wrong shape (object not array) falls back to empty', () => {
    const storage = mockStorage()
    storage.getItem = () => JSON.stringify({ rows: [] })
    const result = readCache(storage)
    expect(result).toEqual([])
  })

  it('storage.getItem throwing doesn\'t crash', () => {
    const storage = { getItem: () => { throw new Error('private browsing') } }
    const result = readCache(storage)
    expect(result).toEqual([])
  })

  it('writeCache with storage.setItem throwing doesn\'t crash', () => {
    const storage = { setItem: () => { throw new Error('quota exceeded') } }
    expect(() => writeCache(storage, [row(1)])).not.toThrow()
  })

  it('readCache filters out null elements', () => {
    const storage = mockStorage()
    storage.getItem = () => JSON.stringify([null])
    const result = readCache(storage)
    expect(result).toEqual([])
  })

  it('readCache filters out rows missing unblocks field', () => {
    const storage = mockStorage()
    const goodRow = row(1)
    const badRow = { ...row(2), unblocks: undefined }
    storage.getItem = () => JSON.stringify([goodRow, badRow])
    const result = readCache(storage)
    expect(result).toHaveLength(1)
    expect(result[0].number).toBe(1)
  })

  it('readCache filters out rows missing number field', () => {
    const storage = mockStorage()
    const goodRow = row(1)
    const badRow = { ...row(2), number: undefined }
    storage.getItem = () => JSON.stringify([goodRow, badRow])
    const result = readCache(storage)
    expect(result).toHaveLength(1)
    expect(result[0].number).toBe(1)
  })

  it('readCache filters out rows missing repo field', () => {
    const storage = mockStorage()
    const goodRow = row(1)
    const badRow = { ...row(2), repo: undefined }
    storage.getItem = () => JSON.stringify([goodRow, badRow])
    const result = readCache(storage)
    expect(result).toHaveLength(1)
    expect(result[0].number).toBe(1)
  })

  it('readCache keeps rows missing project field (cosmetic, not a validity requirement)', () => {
    const storage = mockStorage()
    const rowNoProject = { ...row(1), project: undefined }
    storage.getItem = () => JSON.stringify([rowNoProject])
    const result = readCache(storage)
    expect(result).toHaveLength(1)
    expect(result[0].number).toBe(1)
  })

  it('readCache validates unblocks is an array', () => {
    const storage = mockStorage()
    const badRow = { ...row(1), unblocks: 'not-an-array' }
    storage.getItem = () => JSON.stringify([badRow])
    const result = readCache(storage)
    expect(result).toEqual([])
  })
})

describe('storage: readSortPref / writeSortPref', () => {
  const mockStorage = () => {
    const data = {}
    return {
      getItem: (key) => data[key],
      setItem: (key, value) => { data[key] = value }
    }
  }

  it('readSortPref on empty storage defaults to unblocks', () => {
    const storage = mockStorage()
    const result = readSortPref(storage)
    expect(result).toBe('unblocks')
  })

  it('writeSortPref then readSortPref round-trips', () => {
    const storage = mockStorage()
    writeSortPref(storage, 'priority')
    expect(readSortPref(storage)).toBe('priority')
  })

  it('readSortPref on invalid value defaults to unblocks', () => {
    const storage = mockStorage()
    storage.getItem = () => 'invalid-sort-key'
    const result = readSortPref(storage)
    expect(result).toBe('unblocks')
  })
})

describe('shouldApply', () => {
  it('true when reqId matches latest', () => {
    expect(shouldApply(123, 123)).toBe(true)
  })

  it('false when reqId is older than latest', () => {
    expect(shouldApply(123, 456)).toBe(false)
  })

  it('false when reqId is newer than latest (shouldn\'t happen but defensive)', () => {
    expect(shouldApply(456, 123)).toBe(false)
  })
})

describe('readCache: unblocks.count and priority normalization', () => {
  const mockStorage = () => {
    const data = {}
    return {
      getItem: (key) => data[key],
      setItem: (key, value) => { data[key] = value }
    }
  }

  it('readCache drops a row with missing unblocks.count', () => {
    const storage = mockStorage()
    const badRow = { ...row(1), unblocks: { items: [] } } // missing count
    storage.getItem = () => JSON.stringify([badRow])
    const result = readCache(storage)
    expect(result).toEqual([])
  })

  it('readCache drops a row with non-numeric unblocks.count', () => {
    const storage = mockStorage()
    const badRow = { ...row(1), unblocks: { count: '3', items: [] } } // string, not number
    storage.getItem = () => JSON.stringify([badRow])
    const result = readCache(storage)
    expect(result).toEqual([])
  })

  it('readCache normalizes malformed priority values to null, keeps the row', () => {
    const storage = mockStorage()
    const rows = [
      { ...row(1, { priority: 'urgent' }) },
      { ...row(2, { priority: 'p9' }) },
      { ...row(3, { priority: 'P0' }) },
      { ...row(4, { priority: 5 }) },
      { ...row(5, { priority: {} }) }
    ]
    storage.getItem = () => JSON.stringify(rows)
    const result = readCache(storage)
    expect(result).toHaveLength(5) // all rows kept
    expect(result[0].number).toBe(1)
    expect(result[0].priority).toBe(null)
    expect(result[4].priority).toBe(null)
  })

  it('readCache leaves valid priority values unchanged', () => {
    const storage = mockStorage()
    const rows = [
      { ...row(1, { priority: 'p0' }) },
      { ...row(2, { priority: 'p1' }) },
      { ...row(3, { priority: 'p2' }) },
      { ...row(4, { priority: 'p3' }) }
    ]
    storage.getItem = () => JSON.stringify(rows)
    const result = readCache(storage)
    expect(result).toHaveLength(4)
    expect(result[0].priority).toBe('p0')
    expect(result[1].priority).toBe('p1')
    expect(result[2].priority).toBe('p2')
    expect(result[3].priority).toBe('p3')
  })

  it('readCache normalizes a row with no priority field to null', () => {
    const storage = mockStorage()
    const rowNoField = { ...row(1), priority: undefined }
    storage.getItem = () => JSON.stringify([rowNoField])
    const result = readCache(storage)
    expect(result).toHaveLength(1)
    expect(result[0].priority).toBe(null)
  })
})

describe('emptyStateText', () => {
  it('loading status returns loading message', () => {
    expect(emptyStateText('loading')).toBe('Loading…')
  })

  it('error status returns error message (not the "Nothing" fallback)', () => {
    const text = emptyStateText('error')
    expect(text).not.toBe('Nothing needs you right now.')
    expect(text).toContain("Couldn't check")
  })

  it('ok status returns nothing message', () => {
    expect(emptyStateText('ok')).toBe('Nothing needs you right now.')
  })

  it('unknown status defaults to nothing message', () => {
    expect(emptyStateText('unknown')).toBe('Nothing needs you right now.')
  })
})

describe('freshnessText', () => {
  it('error with no lastUpdated returns "update failed" exactly', () => {
    const text = freshnessText({ status: 'error', error: 'boom', lastUpdated: null })
    expect(text).toBe('update failed')
  })

  it('error with lastUpdated shows age of cached data', () => {
    const now = Date.now()
    const oneHourAgo = now - 3600000
    const text = freshnessText({ status: 'error', error: 'boom', lastUpdated: oneHourAgo, now })
    expect(text).toContain('showing data from')
    expect(text).toContain(' h ago')
  })

  it('loading status returns updating message', () => {
    expect(freshnessText({ status: 'loading', error: null, lastUpdated: null })).toBe('updating…')
  })

  it('ok status with lastUpdated returns age', () => {
    const now = Date.now()
    const fiveMinutesAgo = now - 300000
    const text = freshnessText({ status: 'ok', error: null, lastUpdated: fiveMinutesAgo, now })
    expect(text).toContain('updated')
    expect(text).toContain(' min ago')
  })

  it('ok status with no lastUpdated returns loading', () => {
    expect(freshnessText({ status: 'ok', error: null, lastUpdated: null })).toBe('loading…')
  })
})

describe('initialViewState', () => {
  const mockStorage = () => {
    const data = {}
    return {
      getItem: (key) => data[key],
      setItem: (key, value) => { data[key] = value }
    }
  }

  it('on empty cache, status is loading and rows empty', () => {
    const storage = mockStorage()
    const state = initialViewState(storage)
    expect(state.status).toBe('loading')
    expect(state.rows).toEqual([])
  })

  it('on cache with valid rows, status is ok and rows populated', () => {
    const storage = mockStorage()
    const rows = [row(1), row(2)]
    writeCache(storage, rows)
    const state = initialViewState(storage)
    expect(state.status).toBe('ok')
    expect(state.rows).toHaveLength(2)
    expect(state.rows[0].number).toBe(1)
  })

  it('initialViewState initializes all expected fields', () => {
    const storage = mockStorage()
    const state = initialViewState(storage)
    expect(state).toHaveProperty('rows')
    expect(state).toHaveProperty('sortKey')
    expect(state).toHaveProperty('lastUpdated', null)
    expect(state).toHaveProperty('status')
    expect(state).toHaveProperty('error', null)
    expect(state).toHaveProperty('page', 1)
    expect(state).toHaveProperty('latestReqId', 0)
  })
})

describe('applyFetchError', () => {
  it('sets status and error while preserving rows', () => {
    const prevState = {
      rows: [row(1), row(2)],
      status: 'ok',
      error: null,
      lastUpdated: Date.now()
    }
    const result = applyFetchError(prevState, 'Network error')
    expect(result.status).toBe('error')
    expect(result.error).toBe('Network error')
    expect(result.rows).toEqual(prevState.rows)
    expect(result.lastUpdated).toBe(prevState.lastUpdated)
  })

  it('preserves all other state fields', () => {
    const prevState = {
      rows: [row(1)],
      sortKey: 'priority',
      lastUpdated: 12345,
      status: 'ok',
      error: null,
      page: 2,
      latestReqId: 5
    }
    const result = applyFetchError(prevState, 'Timeout')
    expect(result.sortKey).toBe('priority')
    expect(result.page).toBe(2)
    expect(result.latestReqId).toBe(5)
  })
})
