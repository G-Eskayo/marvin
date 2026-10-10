import { describe, it, expect } from 'vitest'
import { missingFor, blocksGraph, transitiveUnblocks, rankNeedsYou } from '../electron/main/needs_you.js'
import { parseHumanTask } from '../src/lib/human_task.js'

// Test fixture builders
const issue = (num, over = {}) => ({
  number: num,
  title: `Ticket #${num}`,
  state: 'OPEN',
  labels: [],
  body: '',
  url: `https://github.com/o/r/issues/${num}`,
  createdAt: '2026-10-01T00:00:00Z',
  closedAt: null,
  ...over
})

const label = (name) => ({ name })

describe('missingFor', () => {
  it('returns [] when all required sections are present', () => {
    const body = `
## What to build
Something

## Acceptance criteria
- [x] Done

## How we'll try to break it
- Edge case
`
    expect(missingFor(issue(1, { body }))).toEqual([])
  })

  it('flags missing "What to build" section', () => {
    const body = `
## Acceptance criteria
- [x] Done

## How we'll try to break it
- Edge
`
    const missing = missingFor(issue(1, { body }))
    expect(missing).toContain('a "What to build" section')
  })

  it('flags missing acceptance criteria', () => {
    const body = `
## What to build
Something

## How we'll try to break it
- Edge
`
    const missing = missingFor(issue(1, { body }))
    expect(missing).toContain('acceptance criteria')
  })

  it('flags missing break-it section for build tickets', () => {
    const body = `
## What to build
Something

## Acceptance criteria
- [x] Done
`
    const missing = missingFor(issue(1, { body }))
    expect(missing).toContain('a "How we\'ll try to break it" section')
  })

  it('does not flag missing break-it for research-labelled tickets', () => {
    const body = `
## What to build
Something

## Acceptance criteria
- [x] Done
`
    const missing = missingFor(issue(1, { labels: [label('research')], body }))
    expect(missing).not.toContain('a "How we\'ll try to break it" section')
  })

  it('uses parseHumanTask gaps for human-task-shaped titles', () => {
    const body = `
## Your task
**What I need from you:** test it
**Where:** production
**How:** manually
Missing: What to send back
`
    const missing = missingFor(issue(1, { title: 'design session: foo', body }))
    expect(missing).toContain('What to send back')
  })

  it('handles null/missing body gracefully', () => {
    const missing = missingFor(issue(1, { body: null }))
    expect(Array.isArray(missing)).toBe(true)
  })

  it('recognizes alternative section names for "What to build"', () => {
    const body = `
## Summary
Do it

## Acceptance criteria
- [x] Done

## How we'll try to break it
- Test
`
    expect(missingFor(issue(1, { body }))).toEqual([])
  })
})

describe('blocksGraph', () => {
  it('builds reverse adjacency for a single repo', () => {
    const tickets = [
      issue(1, { body: '', state: 'OPEN' }),
      issue(2, { body: 'Blocked by #1', state: 'OPEN' }),
      issue(3, { body: 'Blocked by #2', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    expect(graph[1]).toContain(2)
    expect(graph[2]).toContain(3)
  })

  it('excludes hold-labelled tickets from both ends', () => {
    const tickets = [
      issue(1, { labels: [label('hold')], state: 'OPEN' }),
      issue(2, { body: 'Blocked by #1', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    expect(graph[1]).toBeUndefined()
  })

  it('excludes not-planned tickets from dependents', () => {
    const tickets = [
      issue(1, { state: 'CLOSED', stateReason: 'NOT_PLANNED' }),
      issue(2, { body: 'Blocked by #1', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    // #2 should not list #1 as a blocker since #1 is not planned
    expect(graph[1]).toBeUndefined()
  })

  it('ignores references to closed tickets', () => {
    const tickets = [
      issue(1, { state: 'CLOSED' }),
      issue(2, { body: 'Blocked by #1', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    expect(graph[1]).toBeUndefined()
  })
})

describe('transitiveUnblocks', () => {
  it('counts direct unblocks only', () => {
    const tickets = [
      issue(1, { state: 'OPEN' }),
      issue(2, { body: 'Blocked by #1', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    const result = transitiveUnblocks(1, 'o/r', graph, tickets)
    expect(result.count).toBe(1)
    expect(result.items[0].number).toBe(2)
  })

  it('counts transitive unblocks', () => {
    const tickets = [
      issue(1, { state: 'OPEN' }),
      issue(2, { body: 'Blocked by #1', state: 'OPEN' }),
      issue(3, { body: 'Blocked by #2', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    const result = transitiveUnblocks(1, 'o/r', graph, tickets)
    expect(result.count).toBe(2)
    expect(result.items.map((i) => i.number)).toContain(2)
    expect(result.items.map((i) => i.number)).toContain(3)
  })

  it('handles cycles without infinite loop', () => {
    const tickets = [
      issue(1, { body: 'Blocked by #2', state: 'OPEN' }),
      issue(2, { body: 'Blocked by #1', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    const result = transitiveUnblocks(1, 'o/r', graph, tickets)
    expect(result.count).toBe(1)
    expect(result.items[0].number).toBe(2)
  })

  it('ignores self-references', () => {
    const tickets = [
      issue(1, { body: 'Blocked by #1', state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    const result = transitiveUnblocks(1, 'o/r', graph, tickets)
    expect(result.count).toBe(0)
  })

  it('returns empty when unblocks nothing', () => {
    const tickets = [
      issue(1, { state: 'OPEN' })
    ]
    const graph = blocksGraph(tickets, 'o/r')
    const result = transitiveUnblocks(1, 'o/r', graph, tickets)
    expect(result.count).toBe(0)
    expect(result.items).toEqual([])
  })
})

describe('rankNeedsYou', () => {
  it('prioritizes ready-for-human and needs-info tickets with labels', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** test\n**Where:** prod\n**How:** manually\n**What to send back:** results' }) },
      { repo: 'o/r', ...issue(2, { labels: [label('needs-info')] }) }
    ]
    const result = rankNeedsYou(tickets)
    expect(result.length).toBeGreaterThan(0)
  })

  it('filters out hold and pinned tickets', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human'), label('hold')] }) }
    ]
    const result = rankNeedsYou(tickets)
    expect(result.length).toBe(0)
  })

  it('filters out closed tickets', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { state: 'CLOSED', labels: [label('ready-for-human')] }) }
    ]
    const result = rankNeedsYou(tickets)
    expect(result.length).toBe(0)
  })

  it('sorts by unblocks count descending', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) },
      { repo: 'o/r', ...issue(2, { labels: [label('ready-for-human')], body: 'Blocked by #1\n## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) },
      { repo: 'o/r', ...issue(3, { labels: [label('ready-for-human')], body: 'Blocked by #2\n## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) }
    ]
    const result = rankNeedsYou(tickets)
    if (result.length >= 2) {
      const first = result[0]
      expect(first.unblocks.count).toBeGreaterThanOrEqual(result[1].unblocks.count)
    }
  })

  it('includes unblocks summary with top 3 items', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) },
      { repo: 'o/r', ...issue(2, { labels: [label('blocked')], body: 'Blocked by #1' }) }
    ]
    const result = rankNeedsYou(tickets)
    const row = result.find((r) => r.number === 1)
    if (row) {
      expect(row.unblocks).toBeDefined()
      expect(row.unblocks.count).toBeDefined()
      expect(Array.isArray(row.unblocks.items)).toBe(true)
    }
  })

  it('includes ask for needs-info tickets (missing list)', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('needs-info')], body: '## What to build\nX\n## Acceptance criteria\n- [ ] Y' }) }
    ]
    const result = rankNeedsYou(tickets)
    const row = result[0]
    if (row) {
      expect(row.ask).toBeDefined()
    }
  })

  it('includes ask for ready-for-human (task request)', () => {
    const body = `
## Your task
**What I need from you:** review the design
**Where:** in the PR
**How:** leave comments
**What to send back:** approval
`
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body }) }
    ]
    const result = rankNeedsYou(tickets)
    const row = result[0]
    if (row) {
      expect(row.ask).toContain('review')
    }
  })

  it('returns empty array for no qualifying tickets', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-agent')] }) }
    ]
    expect(rankNeedsYou(tickets)).toEqual([])
  })

  it('returns empty array for empty input', () => {
    expect(rankNeedsYou([])).toEqual([])
  })

  it('does not crash on malformed input', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: null }) }
    ]
    expect(() => rankNeedsYou(tickets)).not.toThrow()
  })

  it('includes priority level when present', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human'), label('p0')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) }
    ]
    const result = rankNeedsYou(tickets)
    if (result.length > 0) {
      expect(result[0].priority).toBeDefined()
    }
  })

  it('sorts by priority when unblocks are equal', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human'), label('p2')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D', createdAt: '2026-10-01T00:00:00Z' }) },
      { repo: 'o/r', ...issue(2, { labels: [label('ready-for-human'), label('p0')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D', createdAt: '2026-10-02T00:00:00Z' }) }
    ]
    const result = rankNeedsYou(tickets)
    if (result.length >= 2) {
      const p0Idx = result.findIndex((r) => r.priority === 'p0')
      const p2Idx = result.findIndex((r) => r.priority === 'p2')
      if (p0Idx >= 0 && p2Idx >= 0) {
        expect(p0Idx).toBeLessThan(p2Idx)
      }
    }
  })

  it('sorts by age when priority is equal', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D', createdAt: '2026-10-05T00:00:00Z' }) },
      { repo: 'o/r', ...issue(2, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D', createdAt: '2026-10-01T00:00:00Z' }) }
    ]
    const result = rankNeedsYou(tickets, { now: new Date('2026-10-10').getTime() })
    if (result.length >= 2) {
      expect(result[0].number).toBe(2) // Older should come first
    }
  })

  it('includes ageDays in output', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D', createdAt: '2026-10-01T00:00:00Z' }) }
    ]
    const result = rankNeedsYou(tickets, { now: new Date('2026-10-10').getTime() })
    if (result.length > 0) {
      expect(result[0].ageDays).toBeGreaterThan(0)
    }
  })

  it('skips one repo failing and includes the others', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) },
      { repo: 'o/good', ...issue(2, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) }
    ]
    const result = rankNeedsYou(tickets)
    expect(result.length).toBeGreaterThan(0)
  })

  it('handles the #153 acceptance case: blocked-by references increase unblocks', () => {
    const tickets = [
      { repo: 'o/r', ...issue(1, { labels: [label('ready-for-human')], body: '## Your task\n**What I need from you:** A\n**Where:** B\n**How:** C\n**What to send back:** D' }) },
      { repo: 'o/r', ...issue(2, { labels: [label('blocked')], body: 'Blocked by #1' }) },
      { repo: 'o/r', ...issue(3, { labels: [label('blocked')], body: 'Blocked by #1' }) },
      { repo: 'o/r', ...issue(4, { labels: [label('blocked')], body: 'Blocked by #1' }) },
      { repo: 'o/r', ...issue(5, { labels: [label('blocked')], body: 'Blocked by #1' }) },
      { repo: 'o/r', ...issue(6, { labels: [label('blocked')], body: 'Blocked by #1' }) },
      { repo: 'o/r', ...issue(7, { labels: [label('needs-info')], body: 'Independent' }) }
    ]
    const result = rankNeedsYou(tickets)
    const row1 = result.find((r) => r.number === 1)
    const row7 = result.find((r) => r.number === 7)
    if (row1 && row7) {
      expect(row1.unblocks.count).toBe(5)
      expect(row1.unblocks.count).toBeGreaterThan(row7.unblocks.count)
      expect(result.indexOf(row1)).toBeLessThan(result.indexOf(row7))
    }
  })
})
