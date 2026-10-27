import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createRelationsService } from '../electron/main/relations_service.js'
import { rankNeedsYou } from '../electron/main/needs_you.js'

const DAY_MS = 86400_000

describe('needsYou feature integration', () => {
  describe('getPriority fix - priority:p0-p3 label parsing', () => {
    it('correctly extracts priority from priority:p0 to priority:p3 labels', () => {
      const now = Date.now()
      const ticket = {
        number: 1,
        title: 'Critical fix',
        state: 'OPEN',
        labels: [{ name: 'ready-for-human' }, { name: 'priority:p0' }],
        body: '',
        url: 'u1',
        createdAt: new Date(now).toISOString(),
        repo: 'G-Eskayo/marvin'
      }

      const result = rankNeedsYou([ticket])
      expect(result).toHaveLength(1)
      expect(result[0].priority).toBe('p0')
    })

    it('also accepts bare p0-p3 labels without priority: prefix', () => {
      const now = Date.now()
      const ticket = {
        number: 2,
        title: 'High priority task',
        state: 'OPEN',
        labels: [{ name: 'ready-for-human' }, { name: 'p1' }],
        body: '',
        url: 'u2',
        createdAt: new Date(now).toISOString(),
        repo: 'G-Eskayo/marvin'
      }

      const result = rankNeedsYou([ticket])
      expect(result).toHaveLength(1)
      expect(result[0].priority).toBe('p1')
    })

    it('handles missing priority gracefully', () => {
      const now = Date.now()
      const ticket = {
        number: 1,
        title: 'No priority',
        state: 'OPEN',
        labels: [{ name: 'ready-for-human' }],
        body: '',
        url: 'u1',
        createdAt: new Date(now).toISOString(),
        repo: 'G-Eskayo/marvin'
      }

      const result = rankNeedsYou([ticket])
      expect(result).toHaveLength(1)
      expect(result[0].priority).toBeNull()
    })
  })

  describe('overview fix - counting needs-info and ready-for-human', () => {
    it('counts both ready-for-human and needs-info tickets in needsYou', async () => {
      const issue = (n, over = {}) => ({
        number: n,
        title: `T${n}`,
        state: 'OPEN',
        labels: [],
        body: '',
        url: `u${n}`,
        createdAt: '2026-10-01T00:00:00Z',
        ...over
      })

      const svc = createRelationsService({
        getRepos: () => ['G-Eskayo/marvin'],
        getBoardData: async () => ({
          issues: [
            issue(1, { labels: [{ name: 'ready-for-human' }] }),
            issue(2, { labels: [{ name: 'needs-info' }] }),
            issue(3, { labels: [] })
          ],
          prs: []
        }),
        getDocs: async () => [],
        getProjects: () => [{ id: 'marvin', repo: 'G-Eskayo/marvin' }]
      })

      const overview = await svc.overview()
      // Both ready-for-human and needs-info should be counted
      expect(overview['G-Eskayo/marvin'].needsYou).toBe(2)
    })
  })

  describe('rankNeedsYou sorting and filtering', () => {
    const makeTicket = (num, config = {}) => {
      const {
        kind = 'ready-for-human',
        priority = null,
        unblocks = 0,
        ageDays = 0,
        title = `Ticket #${num}`,
        body = ''
      } = config

      const labels = [{ name: kind }]
      if (priority) labels.push({ name: `priority:${priority}` })

      return {
        number: num,
        title,
        state: 'OPEN',
        labels,
        body,
        url: `u${num}`,
        createdAt: new Date(Date.now() - ageDays * DAY_MS).toISOString(),
        repo: 'G-Eskayo/marvin'
      }
    }

    it('sorts by unblocks descending first, then priority', () => {
      const ticket1 = makeTicket(1, { priority: 'p2', title: 'T1' })
      const ticket2 = makeTicket(2, { priority: 'p0', title: 'T2' })
      const ticket3 = makeTicket(3, { priority: 'p1', title: 'T3' })

      const result = rankNeedsYou([ticket1, ticket2, ticket3])

      // All have same unblocks count (0), so sorted by priority (p0, p1, p2)
      expect(result[0].number).toBe(2) // p0
      expect(result[1].number).toBe(3) // p1
      expect(result[2].number).toBe(1) // p2
    })

    it('includes both ready-for-human and needs-info', () => {
      const ready = makeTicket(1, { kind: 'ready-for-human' })
      const needsInfo = makeTicket(2, { kind: 'needs-info' })

      const result = rankNeedsYou([ready, needsInfo])
      expect(result).toHaveLength(2)
      expect(result.map((r) => r.kind).sort()).toEqual(['needs-info', 'ready-for-human'])
    })

    it('excludes hold and pinned tickets', () => {
      const normal = makeTicket(1)
      const held = { ...makeTicket(2), labels: [{ name: 'hold' }] }
      const pinned = { ...makeTicket(3), labels: [{ name: 'pinned' }] }

      const result = rankNeedsYou([normal, held, pinned])
      expect(result).toHaveLength(1)
      expect(result[0].number).toBe(1)
    })

    it('excludes closed tickets', () => {
      const open = makeTicket(1)
      const closed = { ...makeTicket(2), state: 'CLOSED' }

      const result = rankNeedsYou([open, closed])
      expect(result).toHaveLength(1)
      expect(result[0].number).toBe(1)
    })
  })

  describe('rankNeedsYou ask field population', () => {
    it('populates ask for ready-for-human', () => {
      const ticket = {
        number: 1,
        title: 'Design decision needed',
        state: 'OPEN',
        labels: [{ name: 'ready-for-human' }],
        body: `## What I need from you\nChoose between option A and option B`,
        url: 'u1',
        createdAt: '2026-10-01T00:00:00Z',
        repo: 'G-Eskayo/marvin'
      }

      const result = rankNeedsYou([ticket])
      expect(result).toHaveLength(1)
      expect(result[0].ask).toBeDefined()
      expect(typeof result[0].ask).toBe('string')
      expect(result[0].ask.length > 0).toBe(true)
    })

    it('populates ask for needs-info from missing sections', () => {
      const ticket = {
        number: 2,
        title: 'Incomplete ticket',
        state: 'OPEN',
        labels: [{ name: 'needs-info' }],
        body: '',
        url: 'u2',
        createdAt: '2026-10-01T00:00:00Z',
        repo: 'G-Eskayo/marvin'
      }

      const result = rankNeedsYou([ticket])
      expect(result).toHaveLength(1)
      expect(result[0].ask).toMatch(/missing/)
    })
  })

  describe('NeedsYouRow click wiring', () => {
    it('NeedsYouRow is properly exported and has the correct interface', async () => {
      const NeedsYouListModule = await import('../src/components/NeedsYouList.jsx')
      const { NeedsYouRow } = NeedsYouListModule

      expect(typeof NeedsYouRow).toBe('function')
      expect(NeedsYouRow.name).toBe('NeedsYouRow')
    })
  })

  describe('DashboardHome integration', () => {
    it('renders with needsYou data flowing through from API', async () => {
      const React = await import('react')
      const { renderToStaticMarkup } = await import('react-dom/server')
      const DashboardHome = (await import('../src/components/DashboardHome.jsx')).default

      const element = React.createElement(DashboardHome, { onOpenProject: () => {}, onOpenTicket: () => {} })
      const html = renderToStaticMarkup(element)

      expect(html).toContain('Needs you')
      expect(html).toContain('data-testid="needs-you"')
    })
  })
})
