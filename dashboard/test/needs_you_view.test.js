import { describe, it, expect } from 'vitest'
import { paginate, sortRows, pillFor, projectName, mergeNeedsYouResult, readSortChoice, writeSortChoice } from '../src/lib/needs_you_view.js'

const row = (num, over = {}) => ({
  repo: 'G-Eskayo/marvin',
  number: num,
  title: `Ticket #${num}`,
  url: `https://github.com/G-Eskayo/marvin/issues/${num}`,
  kind: 'ready-for-human',
  unblocks: { count: 0, items: [] },
  ask: 'needs review',
  priority: null,
  ageDays: 5,
  project: { id: 'marvin', repo: 'G-Eskayo/marvin' },
  ...over
})

describe('paginate', () => {
  it('returns rows for the given page', () => {
    const rows = [row(1), row(2), row(3), row(4), row(5), row(6)]
    const result = paginate(rows, 0, 2)
    expect(result.rows).toHaveLength(2)
    expect(result.rows[0].number).toBe(1)
    expect(result.rows[1].number).toBe(2)
  })

  it('clamps page to valid range', () => {
    const rows = [row(1), row(2)]
    expect(paginate(rows, -1, 2).page).toBe(0)
    expect(paginate(rows, 10, 2).page).toBe(0)
  })

  it('returns correct totalPages', () => {
    const rows = [row(1), row(2), row(3)]
    expect(paginate(rows, 0, 2).totalPages).toBe(2)
    expect(paginate(rows, 1, 2).totalPages).toBe(2)
  })

  it('handles empty rows', () => {
    const result = paginate([], 0, 5)
    expect(result.rows).toEqual([])
    expect(result.totalPages).toBe(1)
    expect(result.page).toBe(0)
  })
})

describe('sortRows', () => {
  it('sorts by unblocks descending (default)', () => {
    const rows = [row(1, { unblocks: { count: 1, items: [] } }), row(2, { unblocks: { count: 5, items: [] } }), row(3, { unblocks: { count: 3, items: [] } })]
    const result = sortRows(rows, 'unblocks')
    expect(result[0].number).toBe(2)
    expect(result[1].number).toBe(3)
    expect(result[2].number).toBe(1)
  })

  it('sorts by priority ascending', () => {
    const rows = [row(1, { priority: 'p2' }), row(2, { priority: 'p0' }), row(3, { priority: null })]
    const result = sortRows(rows, 'priority')
    expect(result[0].number).toBe(2) // p0
    expect(result[1].number).toBe(1) // p2
    expect(result[2].number).toBe(3) // null (99)
  })

  it('sorts by oldest (highest ageDays first)', () => {
    const rows = [row(1, { ageDays: 5 }), row(2, { ageDays: 20 }), row(3, { ageDays: 10 })]
    const result = sortRows(rows, 'oldest')
    expect(result[0].number).toBe(2) // 20 days
    expect(result[1].number).toBe(3) // 10 days
    expect(result[2].number).toBe(1) // 5 days
  })

  it('sorts by project name', () => {
    const rows = [
      row(1, { project: { id: 'zzz', repo: 'G-Eskayo/zzz' } }),
      row(2, { project: { id: 'aaa', repo: 'G-Eskayo/aaa' } }),
      row(3, { project: { id: 'mmm', repo: 'G-Eskayo/mmm' } })
    ]
    const boards = {
      'G-Eskayo/zzz': { name: 'Project ZZZ' },
      'G-Eskayo/aaa': { name: 'Project AAA' },
      'G-Eskayo/mmm': { name: 'Project MMM' }
    }
    const result = sortRows(rows, 'project', boards)
    expect(result[0].number).toBe(2) // aaa
    expect(result[1].number).toBe(3) // mmm
    expect(result[2].number).toBe(1) // zzz
  })

  it('preserves original array', () => {
    const rows = [row(1), row(2)]
    sortRows(rows, 'unblocks')
    expect(rows).toHaveLength(2)
  })
})

describe('pillFor', () => {
  it('returns grey tone for p2/p3/no priority', () => {
    const r1 = pillFor(row(1, { priority: 'p2' }))
    expect(r1.tone).toBe('grey')
    expect(r1.text).not.toContain('P2') // p2/p3 not shown in pill

    const r2 = pillFor(row(2, { priority: null }))
    expect(r2.tone).toBe('grey')
    expect(r2.text).not.toContain('P')
  })

  it('returns red tone for p0', () => {
    const r = pillFor(row(1, { priority: 'p0' }))
    expect(r.tone).toBe('red')
    expect(r.text).toContain('P0')
  })

  it('returns orange tone for p1', () => {
    const r = pillFor(row(1, { priority: 'p1' }))
    expect(r.tone).toBe('orange')
    expect(r.text).toContain('P1')
  })

  it('shows "needs answer" for needs-info kind', () => {
    const r = pillFor(row(1, { kind: 'needs-info' }))
    expect(r.text).toContain('needs answer')
  })

  it('shows "needs you" for ready-for-human kind', () => {
    const r = pillFor(row(1, { kind: 'ready-for-human' }))
    expect(r.text).toContain('needs you')
  })
})

describe('projectName', () => {
  it('returns board name when found', () => {
    const r = row(1, { project: { id: 'clarity', repo: 'G-Eskayo/clarity-captions' } })
    const boards = { 'G-Eskayo/clarity-captions': { name: 'Clarity Captions' } }
    expect(projectName(r, boards)).toBe('Clarity Captions')
  })

  it('falls back to repo short name when board not found', () => {
    const r = row(1, { project: { id: 'unknown', repo: 'G-Eskayo/unknown-repo' } })
    expect(projectName(r, {})).toBe('unknown-repo')
  })

  it('falls back to row.repo when project.repo is null', () => {
    const r = row(1, { repo: 'G-Eskayo/fallback', project: { id: 'unknown', repo: null } })
    expect(projectName(r, {})).toBe('fallback')
  })

  it('handles missing boards gracefully', () => {
    const r = row(1)
    expect(projectName(r, undefined)).toBe('marvin')
  })
})

describe('mergeNeedsYouResult', () => {
  it('on success: replaces rows and timestamp', () => {
    const prev = { rows: [row(1)], timestamp: 1000, error: null }
    const result = { rows: [row(2), row(3)], error: null }
    const merged = mergeNeedsYouResult(prev, result, { now: 2000 })
    expect(merged.rows).toEqual(result.rows)
    expect(merged.timestamp).toBe(2000)
    expect(merged.error).toBeNull()
  })

  it('on error: keeps prior rows and timestamp', () => {
    const prev = { rows: [row(1)], timestamp: 1000, error: null }
    const result = { error: 'Network error' }
    const merged = mergeNeedsYouResult(prev, result, { now: 2000 })
    expect(merged.rows).toEqual(prev.rows)
    expect(merged.timestamp).toBe(1000)
    expect(merged.error).toBe('Network error')
  })

  it('handles first-ever fetch (no prev)', () => {
    const result = { rows: [row(1)], error: null }
    const merged = mergeNeedsYouResult(undefined, result, { now: 1000 })
    expect(merged.rows).toEqual(result.rows)
    expect(merged.timestamp).toBe(1000)
  })

  it('on error with no prev: keeps empty rows', () => {
    const result = { error: 'Network error' }
    const merged = mergeNeedsYouResult(undefined, result, { now: 1000 })
    expect(merged.rows).toEqual([])
    expect(merged.error).toBe('Network error')
  })

  it('drops stale result (seq < latestSeq)', () => {
    const prev = { rows: [row(2), row(3)], timestamp: 2000, error: null }
    const result = { rows: [row(1)], error: null }
    const merged = mergeNeedsYouResult(prev, result, { seq: 1, latestSeq: 2 })
    expect(merged).toEqual(prev)
  })

  it('accepts result when seq === latestSeq', () => {
    const prev = { rows: [row(1)], timestamp: 1000, error: null }
    const result = { rows: [row(2), row(3)], error: null }
    const merged = mergeNeedsYouResult(prev, result, { now: 2000, seq: 2, latestSeq: 2 })
    expect(merged.rows).toEqual(result.rows)
    expect(merged.timestamp).toBe(2000)
  })

  it('ignores seq/latestSeq when not provided', () => {
    const prev = { rows: [row(1)], timestamp: 1000, error: null }
    const result = { rows: [row(2), row(3)], error: null }
    const merged = mergeNeedsYouResult(prev, result, { now: 2000 })
    expect(merged.rows).toEqual(result.rows)
  })

  it('handles empty rows gracefully', () => {
    const result = { rows: [], error: null }
    const merged = mergeNeedsYouResult(undefined, result, { now: 1000 })
    expect(merged.rows).toEqual([])
    expect(merged.timestamp).toBe(1000)
  })
})

describe('readSortChoice / writeSortChoice', () => {
  it('reads saved sort choice', () => {
    const storage = {
      getItem: () => 'priority',
      setItem: () => {}
    }
    expect(readSortChoice(storage)).toBe('priority')
  })

  it('defaults to "unblocks" when not saved', () => {
    const storage = {
      getItem: () => null,
      setItem: () => {}
    }
    expect(readSortChoice(storage)).toBe('unblocks')
  })

  it('validates against known sort keys', () => {
    const storage = {
      getItem: () => 'invalid',
      setItem: () => {}
    }
    expect(readSortChoice(storage)).toBe('unblocks')
  })

  it('handles storage errors gracefully', () => {
    const storage = {
      getItem: () => { throw new Error('quota') },
      setItem: () => {}
    }
    expect(readSortChoice(storage)).toBe('unblocks')
  })

  it('writes sort choice to storage', () => {
    let saved = null
    const storage = {
      getItem: () => null,
      setItem: (k, v) => { saved = v }
    }
    writeSortChoice(storage, 'priority')
    expect(saved).toBe('priority')
  })

  it('handles write errors silently', () => {
    const storage = {
      getItem: () => null,
      setItem: () => { throw new Error('quota') }
    }
    expect(() => writeSortChoice(storage, 'priority')).not.toThrow()
  })

  it('handles missing storage', () => {
    expect(readSortChoice(null)).toBe('unblocks')
    expect(() => writeSortChoice(null, 'priority')).not.toThrow()
  })
})
