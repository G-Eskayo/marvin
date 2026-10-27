import { describe, it, expect } from 'vitest'
import { createRelationsService } from '../electron/main/relations_service.js'
import { rankNeedsYou } from '../electron/main/needs_you.js'
import { paginate, sortRows, priorityStyle } from '../src/lib/needs_you_view.js'

const DAY_MS = 86400_000
const NOW = Date.parse('2026-10-21T12:00:00Z')

describe('needs_you feature end-to-end', () => {
  const makeTicket = (num, config = {}) => {
    const {
      kind = 'ready-for-human',
      priority = null,
      title = `Ticket #${num}`,
      ageDays = 0
    } = config

    const labels = [{ name: kind }]
    if (priority) labels.push({ name: `priority:${priority}` })

    return {
      number: num,
      title,
      state: 'OPEN',
      labels,
      body: config.body || '',
      url: `https://github.com/G-Eskayo/marvin/issues/${num}`,
      createdAt: new Date(NOW - ageDays * DAY_MS).toISOString(),
      repo: 'G-Eskayo/marvin'
    }
  }

  it('shows a list of tickets that need human input with correct priorities and styling', () => {
    // Create sample data matching the "Done when" requirements
    const p0Ticket = makeTicket(1, {
      kind: 'ready-for-human',
      priority: 'p0',
      title: 'Critical: Fix security vulnerability',
      ageDays: 2
    })

    const p1Ticket = makeTicket(2, {
      kind: 'ready-for-human',
      priority: 'p1',
      title: 'Important: Design decision needed',
      ageDays: 5
    })

    const needsInfoTicket = makeTicket(3, {
      kind: 'needs-info',
      priority: null,
      title: 'Missing requirements - waiting for info',
      ageDays: 1
    })

    // Rank them
    const ranked = rankNeedsYou([p0Ticket, p1Ticket, needsInfoTicket], { now: NOW })

    // Should have all three
    expect(ranked).toHaveLength(3)

    // First should be p0 (highest priority)
    expect(ranked[0].number).toBe(1)
    expect(ranked[0].priority).toBe('p0')
    expect(ranked[0].kind).toBe('ready-for-human')

    // Second should be p1
    expect(ranked[1].number).toBe(2)
    expect(ranked[1].priority).toBe('p1')

    // Third should be needs-info
    expect(ranked[2].number).toBe(3)
    expect(ranked[2].kind).toBe('needs-info')
    expect(ranked[2].priority).toBeNull()
  })

  it('applies correct styling to priority pills', () => {
    const p0Style = priorityStyle('p0', 'ready-for-human')
    expect(p0Style.bg).toBe('bg-red-950')
    expect(p0Style.text).toBe('text-red-300')
    expect(p0Style.label).toBe('P0')

    const p1Style = priorityStyle('p1', 'ready-for-human')
    expect(p1Style.bg).toBe('bg-orange-950')
    expect(p1Style.text).toBe('text-orange-300')

    const p2Style = priorityStyle('p2', 'ready-for-human')
    expect(p2Style.bg).toBe('bg-neutral-900')
    expect(p2Style.text).toBe('text-neutral-400')

    const noPriorityStyle = priorityStyle(null, 'needs-info')
    expect(noPriorityStyle.label).toBe('needs answer')

    const readyNoPriorityStyle = priorityStyle(null, 'ready-for-human')
    expect(readyNoPriorityStyle.label).toBe('needs you')
  })

  it('paginates the needs_you list correctly', () => {
    const tickets = Array.from({ length: 12 }, (_, i) =>
      makeTicket(i + 1, { title: `Ticket ${i + 1}` })
    )

    const ranked = rankNeedsYou(tickets, { now: NOW })

    // First page
    const page0 = paginate(ranked, 0, 5)
    expect(page0.items).toHaveLength(5)
    expect(page0.page).toBe(0)
    expect(page0.total).toBe(12)
    expect(page0.pages).toBe(3)

    // Second page
    const page1 = paginate(ranked, 1, 5)
    expect(page1.items).toHaveLength(5)
    expect(page1.items[0].number).toBe(6)

    // Last page
    const page2 = paginate(ranked, 2, 5)
    expect(page2.items).toHaveLength(2)
    expect(page2.items[0].number).toBe(11)
  })

  it('sorts by priority correctly in view', () => {
    const tickets = [
      makeTicket(1, { priority: 'p2' }),
      makeTicket(2, { priority: 'p0' }),
      makeTicket(3, { priority: 'p1' }),
      makeTicket(4) // No priority
    ]

    const ranked = rankNeedsYou(tickets, { now: NOW })
    const sorted = sortRows(ranked, 'priority')

    // Should be p0, p1, p2, no priority
    expect(sorted[0].priority).toBe('p0')
    expect(sorted[1].priority).toBe('p1')
    expect(sorted[2].priority).toBe('p2')
    expect(sorted[3].priority).toBeNull()
  })

  it('overview counts both ready-for-human and needs-info correctly', async () => {
    const svc = createRelationsService({
      getRepos: () => ['G-Eskayo/marvin', 'G-Eskayo/test'],
      getBoardData: async (repo) => {
        if (repo === 'G-Eskayo/marvin') {
          return {
            issues: [
              {
                number: 1,
                title: 'Ready for human',
                state: 'OPEN',
                labels: [{ name: 'ready-for-human' }],
                body: '',
                url: 'u1',
                createdAt: '2026-10-01T00:00:00Z'
              },
              {
                number: 2,
                title: 'Needs info',
                state: 'OPEN',
                labels: [{ name: 'needs-info' }],
                body: '',
                url: 'u2',
                createdAt: '2026-10-01T00:00:00Z'
              },
              {
                number: 3,
                title: 'In review',
                state: 'OPEN',
                labels: [{ name: 'ready-for-agent' }],
                body: '',
                url: 'u3',
                createdAt: '2026-10-01T00:00:00Z'
              }
            ],
            prs: []
          }
        }
        return { issues: [], prs: [] }
      },
      getDocs: async () => [],
      getProjects: () => [
        { id: 'marvin', repo: 'G-Eskayo/marvin' },
        { id: 'test', repo: 'G-Eskayo/test' }
      ]
    })

    const overview = await svc.overview()

    // Both ready-for-human and needs-info counted; ready-for-agent goes to review column
    expect(overview['G-Eskayo/marvin'].needsYou).toBe(2)
  })

  it('handles empty needs_you list gracefully', () => {
    const empty = []
    const ranked = rankNeedsYou(empty, { now: NOW })

    expect(ranked).toHaveLength(0)

    // Should paginate without error
    const page = paginate(ranked, 0, 5)
    expect(page.total).toBe(0)
    expect(page.items).toHaveLength(0)
  })

  it('preserves correct ageDays calculation', () => {
    const today = makeTicket(1, { ageDays: 0 })
    const yesterday = makeTicket(2, { ageDays: 1 })
    const twoWeeksAgo = makeTicket(3, { ageDays: 14 })

    const ranked = rankNeedsYou([today, yesterday, twoWeeksAgo], { now: NOW })

    expect(ranked[0].ageDays).toBe(14) // Oldest first
    expect(ranked[1].ageDays).toBe(1)
    expect(ranked[2].ageDays).toBe(0)
  })
})
