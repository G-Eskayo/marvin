import { describe, it, expect } from 'vitest'
import { paginate, sortRows, priorityPill, resolveProjectName, readSortPref, writeSortPref, SORT_ORDERS, PAGE_SIZE } from '../src/lib/needs_you_view.js'

// Test fixture
const row = (num, over = {}) => ({
  repo: 'o/r',
  number: num,
  title: `Ticket #${num}`,
  projectId: 'test-proj',
  url: `https://github.com/o/r/issues/${num}`,
  kind: 'ready-for-human',
  unblocks: { count: 0, items: [] },
  ask: 'needs review',
  priority: null,
  ageDays: 0,
  ...over
})

describe('PAGE_SIZE constant', () => {
  it('exports PAGE_SIZE = 5 (test #1)', () => {
    expect(PAGE_SIZE).toBe(5)
  })
})

describe('paginate', () => {
  it('splits rows into pages of given size (test #2)', () => {
    const rows = [row(1), row(2), row(3), row(4), row(5)]
    const result = paginate(rows, 1, 3)
    expect(result.items).toHaveLength(3)
    expect(result.items[0].number).toBe(1)
    expect(result.totalPages).toBe(2)
  })

  it('clamps page to valid range (test #3)', () => {
    const rows = [row(1), row(2)]
    expect(paginate(rows, 0, 1).page).toBe(1)
    expect(paginate(rows, 99, 1).page).toBe(2)
  })

  it('returns totalPages=1 for empty list (test #4)', () => {
    const result = paginate([], 1, PAGE_SIZE)
    expect(result.totalPages).toBe(1)
    expect(result.items).toEqual([])
  })

  it('includes total count (test #5)', () => {
    const rows = [row(1), row(2), row(3)]
    const result = paginate(rows, 1, PAGE_SIZE)
    expect(result.total).toBe(3)
  })

  it('uses PAGE_SIZE as default pageSize (test #6)', () => {
    const rows = Array.from({ length: 12 }, (_, i) => row(i + 1))
    const result = paginate(rows, 1)
    expect(result.items.length).toBe(PAGE_SIZE)
    expect(result.totalPages).toBe(3)
  })

  it('clamps garbage input (test #7)', () => {
    const rows = [row(1), row(2)]
    expect(paginate(rows, -5, -10).page).toBe(1)
    expect(paginate(rows, NaN, NaN).page).toBe(1)
  })
})

describe('sortRows', () => {
  const highImpact = row(1, { unblocks: { count: 5, items: [] }, ageDays: 1 })
  const lowImpact = row(2, { unblocks: { count: 0, items: [] }, ageDays: 1 })
  const p0 = row(3, { priority: 'p0', ageDays: 1 })
  const p2 = row(4, { priority: 'p2', ageDays: 1 })
  const old = row(5, { ageDays: 10 })
  const new_ = row(6, { ageDays: 1 })

  it('unblocks: returns backend order (passthrough) (test #8)', () => {
    const rows = [lowImpact, highImpact]
    const sorted = sortRows(rows, 'unblocks')
    expect(sorted).toEqual(rows)
  })

  it('priority: sorts by priority (asc), then age desc (test #9)', () => {
    const rows = [p2, p0]
    const sorted = sortRows(rows, 'priority')
    expect(sorted[0].number).toBe(3)
    expect(sorted[1].number).toBe(4)
  })

  it('oldest: sorts by age desc (oldest first) (test #10)', () => {
    const rows = [new_, old]
    const sorted = sortRows(rows, 'oldest')
    expect(sorted[0].number).toBe(5)
    expect(sorted[1].number).toBe(6)
  })

  it('project: sorts by project name alphabetically (test #11)', () => {
    const boardA = { repo: 'o/aaa', name: 'AAA' }
    const boardB = { repo: 'o/zzz', name: 'ZZZ' }
    const rowA = row(1, { repo: 'o/aaa', projectId: 'aaa' })
    const rowB = row(2, { repo: 'o/zzz', projectId: 'zzz' })
    const sorted = sortRows([rowB, rowA], 'project', [boardA, boardB])
    expect(sorted[0].number).toBe(1)
    expect(sorted[1].number).toBe(2)
  })

  it('project: handles missing boards gracefully (test #12)', () => {
    const rows = [row(2), row(1)]
    const sorted = sortRows(rows, 'project', [])
    expect(sorted.length).toBe(2)
  })

  it('priority: null priority sorts to 99 (lowest) (test #13)', () => {
    const withPri = row(1, { priority: 'p0' })
    const noPri = row(2, { priority: null })
    const sorted = sortRows([noPri, withPri], 'priority')
    expect(sorted[0].number).toBe(1)
    expect(sorted[1].number).toBe(2)
  })

  it('oldest: NaN ageDays clamps to 0 (test #14)', () => {
    const rows = [row(1, { ageDays: NaN }), row(2, { ageDays: 5 })]
    const sorted = sortRows(rows, 'oldest')
    expect(sorted[0].number).toBe(2)
  })

  it('defaults to unblocks sort (test #15)', () => {
    const rows = [lowImpact, highImpact]
    const sorted = sortRows(rows)
    expect(sorted).toEqual(rows)
  })
})

describe('priorityPill', () => {
  it('returns null for no priority (test #16)', () => {
    expect(priorityPill(null)).toBeNull()
    expect(priorityPill(undefined)).toBeNull()
  })

  it('builds a P0 pill with red styling (test #17)', () => {
    const pill = priorityPill('p0')
    expect(pill.label).toBe('P0')
    expect(pill.level).toBe(0)
    expect(pill.className).toContain('red')
  })

  it('builds P1 with orange, P2 with yellow, P3 with grey (test #18)', () => {
    const p1 = priorityPill('p1')
    const p2 = priorityPill('p2')
    const p3 = priorityPill('p3')
    expect(p1.className).toContain('orange')
    expect(p2.className).toContain('yellow')
    expect(p3.className).toContain('neutral')
  })

  it('accepts kind parameter (not used for color, but accepted) (test #19)', () => {
    const pill = priorityPill('p0', 'needs-info')
    expect(pill.label).toBe('P0')
  })

  it('handles invalid priority level gracefully (test #20)', () => {
    const pill = priorityPill('p99')
    expect(pill.level).toBe(9)
    expect(pill.className).toContain('neutral')
  })
})

describe('resolveProjectName', () => {
  const boards = [
    { repo: 'o/marvin', name: 'MARVIN' },
    { repo: 'o/finance', name: 'Finance OS' }
  ]

  it('returns null for no row (test #21)', () => {
    expect(resolveProjectName(null, boards)).toBeNull()
    expect(resolveProjectName(undefined, boards)).toBeNull()
  })

  it('resolves via projectId when present (test #22)', () => {
    const r = row(1, { repo: 'o/marvin', projectId: 'marvin' })
    expect(resolveProjectName(r, boards)).toBe('MARVIN')
  })

  it('derives projectId from repo if not explicitly set (test #23)', () => {
    const r = row(1, { repo: 'o/marvin', projectId: null })
    expect(resolveProjectName(r, boards)).toBe('MARVIN')
  })

  it('falls back to projectId string if board not found (test #24)', () => {
    const r = row(1, { projectId: 'unknown' })
    expect(resolveProjectName(r, boards)).toBe('unknown')
  })

  it('handles empty boards list (test #25)', () => {
    const r = row(1, { projectId: 'marvin' })
    expect(resolveProjectName(r, [])).toBe('marvin')
  })

  it('handles repo with hyphens/capitals (test #26)', () => {
    const r = row(1, { repo: 'o/My-Killer-App', projectId: null })
    const board = { repo: 'o/My-Killer-App', name: 'My Killer App' }
    expect(resolveProjectName(r, [board])).toBe('My Killer App')
  })

  it('returns null when row.projectId and repo both missing (test #27)', () => {
    const r = row(1, { repo: null, projectId: null })
    expect(resolveProjectName(r, boards)).toBeNull()
  })
})

describe('sort preferences', () => {
  it('reads sort preference from storage, defaulting to unblocks', () => {
    const storage = { getItem: () => '"priority"' }
    expect(readSortPref(storage)).toBe('priority')
    expect(readSortPref({})).toBe('unblocks')
  })

  it('validates sort order, rejecting invalid values', () => {
    const storage = { getItem: () => '"invalid"' }
    expect(readSortPref(storage)).toBe('unblocks')
  })

  it('writes sort preference to storage', () => {
    const items = {}
    const storage = { setItem: (k, v) => { items[k] = v } }
    writeSortPref(storage, 'priority')
    expect(JSON.parse(items['needsyou.sort'])).toBe('priority')
  })

  it('swallows storage errors gracefully', () => {
    const storage = { setItem: () => { throw new Error('quota') } }
    expect(() => writeSortPref(storage, 'oldest')).not.toThrow()
  })
})

describe('SORT_ORDERS constant', () => {
  it('exports the list of valid sort orders', () => {
    expect(SORT_ORDERS).toEqual(['unblocks', 'priority', 'oldest', 'project'])
  })
})
