import { describe, it, expect } from 'vitest'
import { paginate, sortRows, pillFor, shouldApplyCachedRows, describeNeedsYouRow } from '../src/lib/needs_you_view.js'

describe('needs_you_view', () => {
  const row = (n, over = {}) => ({
    repo: 'G-Eskayo/marvin',
    number: n,
    title: `T${n}`,
    url: `u${n}`,
    kind: 'ready-for-human',
    unblocks: { count: 0, items: [] },
    ask: 'info',
    priority: null,
    ageDays: 0,
    ...over
  })

  // Test 14: paginate returns correct page size
  it('paginate returns items for the given page (default 10 per page)', () => {
    const rows = [row(1), row(2), row(3)]
    const p = paginate(rows, 0, 10)
    expect(p.items).toHaveLength(3)
    expect(p.total).toBe(3)
    expect(p.count).toBe(3)
  })

  // Test 15: paginate handles multiple pages
  it('paginate handles multiple pages correctly', () => {
    const rows = Array.from({ length: 25 }, (_, i) => row(i + 1))
    const p0 = paginate(rows, 0, 10)
    const p1 = paginate(rows, 1, 10)
    const p2 = paginate(rows, 2, 10)
    expect(p0.items).toHaveLength(10)
    expect(p1.items).toHaveLength(10)
    expect(p2.items).toHaveLength(5)
    expect(p0.items[0].number).toBe(1)
    expect(p1.items[0].number).toBe(11)
    expect(p2.items[0].number).toBe(21)
  })

  // Test 16: paginate handles empty rows
  it('paginate handles empty rows', () => {
    const p = paginate([], 0, 10)
    expect(p.items).toHaveLength(0)
    expect(p.total).toBe(0)
    expect(p.count).toBe(0)
  })

  // Test 17: sortRows default sorts by unblocks desc, priority asc, age desc
  it('sortRows default: unblocks desc, priority asc, age desc', () => {
    const rows = [
      row(1, { unblocks: { count: 0 }, priority: 'p1', ageDays: 10 }),
      row(2, { unblocks: { count: 2 }, priority: 'p0', ageDays: 5 }),
      row(3, { unblocks: { count: 2 }, priority: 'p1', ageDays: 20 })
    ]
    const sorted = sortRows(rows)
    // Rows 2 and 3 both have unblocks count 2 (tied for highest)
    // Row 2 has priority p0 (0), Row 3 has priority p1 (1)
    // p0 comes before p1, so Row 2 comes first
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(3)
    expect(sorted[2].number).toBe(1)
  })

  // Test 18: sortRows priority sort
  it('sortRows priority sort orders by priority asc', () => {
    const rows = [
      row(1, { priority: 'p3' }),
      row(2, { priority: 'p0' }),
      row(3, { priority: 'p1' })
    ]
    const sorted = sortRows(rows, 'priority')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(3)
    expect(sorted[2].number).toBe(1)
  })

  // Test 19: sortRows age sort
  it('sortRows age sort orders by age desc (oldest first)', () => {
    const rows = [
      row(1, { ageDays: 5 }),
      row(2, { ageDays: 20 }),
      row(3, { ageDays: 10 })
    ]
    const sorted = sortRows(rows, 'age')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(3)
    expect(sorted[2].number).toBe(1)
  })

  // Test 20: sortRows unblocks sort
  it('sortRows unblocks sort orders by unblocks count desc', () => {
    const rows = [
      row(1, { unblocks: { count: 1 } }),
      row(2, { unblocks: { count: 5 } }),
      row(3, { unblocks: { count: 3 } })
    ]
    const sorted = sortRows(rows, 'unblocks')
    expect(sorted[0].number).toBe(2)
    expect(sorted[1].number).toBe(3)
    expect(sorted[2].number).toBe(1)
  })

  // Test 21: pillFor returns correct class for p0
  it('pillFor returns red pill for p0', () => {
    const pill = pillFor(row(1, { priority: 'p0' }))
    expect(pill.label).toBe('P0')
    expect(pill.className).toContain('red-900')
  })

  // Test 22: pillFor returns correct class for p1 and p2
  it('pillFor returns correct colors for p1 and p2', () => {
    const p1 = pillFor(row(1, { priority: 'p1' }))
    const p2 = pillFor(row(1, { priority: 'p2' }))
    expect(p1.label).toBe('P1')
    expect(p1.className).toContain('orange-900')
    expect(p2.label).toBe('P2')
    expect(p2.className).toContain('yellow-800')
  })

  // Test 23: pillFor returns empty for null priority
  it('pillFor returns empty for null priority', () => {
    const pill = pillFor(row(1, { priority: null }))
    expect(pill.label).toBe('')
    expect(pill.className).toBe('')
  })

  // Test 24: shouldApplyCachedRows returns false for empty/stale cache
  it('shouldApplyCachedRows returns false for missing/empty rows', () => {
    expect(shouldApplyCachedRows(null)).toBe(false)
    expect(shouldApplyCachedRows(undefined)).toBe(false)
    expect(shouldApplyCachedRows({})).toBe(false)
    expect(shouldApplyCachedRows({ rows: [] })).toBe(false)
    expect(shouldApplyCachedRows({ rows: [], at: Date.now() })).toBe(false)
  })

  // Test 25: shouldApplyCachedRows returns true for recent non-empty cache
  it('shouldApplyCachedRows returns true for recent cache with rows', () => {
    const recent = { rows: [row(1)], at: Date.now() - 5000 } // 5 seconds old
    expect(shouldApplyCachedRows(recent)).toBe(true)
  })

  // Test 26: describeNeedsYouRow extracts and formats row data
  it('describeNeedsYouRow extracts title, number, repo, ask, priority, pill, unblocks, kind', () => {
    const testRow = row(5, { ask: 'decision', priority: 'p2', kind: 'ready-for-human' })
    const desc = describeNeedsYouRow(testRow)
    expect(desc.title).toBe('T5')
    expect(desc.number).toBe(5)
    expect(desc.repo).toBe('G-Eskayo/marvin')
    expect(desc.repoShort).toBe('marvin')
    expect(desc.ask).toBe('decision')
    expect(desc.priority).toBe('p2')
    expect(desc.pill.label).toBe('P2')
    expect(desc.kind).toBe('ready-for-human')
  })

  // Test 27: describeNeedsYouRow escapes malicious content in ask field
  it('describeNeedsYouRow does not sanitize but preserves ask as-is (escape at render time)', () => {
    const testRow = row(10, { ask: '<script>alert("xss")</script>' })
    const desc = describeNeedsYouRow(testRow)
    // React will escape this when rendering; the function just passes it through
    expect(desc.ask).toBe('<script>alert("xss")</script>')
  })
})
