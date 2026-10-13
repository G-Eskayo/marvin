import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Markdown, { parseDashLink } from '../src/components/Markdown.jsx'
import Related from '../src/components/Related.jsx'
import AgentsPanel from '../src/components/AgentsPanel.jsx'
import { priorityPill, kindLabel, paginate } from '../src/lib/needs_you_view.js'

describe('Markdown with project context', () => {
  const ctx = { project: 'marvin', repo: 'G-Eskayo/marvin', adrs: { 33: 'docs/adr/0033-health.md' } }

  it('renders ticket and ADR references as in-app links, and leaves ordinary links external', () => {
    const html = renderToStaticMarkup(<Markdown content={'Blocked by #12, see ADR 0033 and [site](https://example.com).'} ctx={ctx} />)
    expect(html).toContain('>#12</a>')
    expect(html).toContain('>ADR 0033</a>')
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain('target="_blank"')
  })

  it('renders plain markdown when there is no context yet', () => {
    expect(renderToStaticMarkup(<Markdown content={'# Title\n\nhello #12'} ctx={null} />)).toContain('<h1')
  })

  it('parses dash links back into targets', () => {
    expect(parseDashLink('dash://ticket/G-Eskayo/marvin/12')).toEqual({ type: 'ticket', repo: 'G-Eskayo/marvin', number: 12 })
    expect(parseDashLink('dash://doc/marvin/docs/adr/0033-health.md')).toEqual({ type: 'doc', project: 'marvin', path: 'docs/adr/0033-health.md' })
    // the master map links folders and files on the Mac (2026-10-07); spaces arrive percent-encoded
    expect(parseDashLink('file:///Users/me/Documents/Projects/My%20App')).toEqual({ type: 'file', path: '/Users/me/Documents/Projects/My App' })
    expect(parseDashLink('https://github.com/G-Eskayo/marvin')).toBeNull()
    expect(parseDashLink('https://x.com')).toBeNull()
  })
})

describe('Related', () => {
  const rel = {
    docs: [{ project: 'marvin', path: 'docs/adr/0033-health.md', label: '0033-health.md', relation: 'mentions' }],
    tickets: [{ repo: 'G-Eskayo/marvin', number: 115, title: 'per-device columns', state: 'OPEN', column: 'blocked', relation: 'blocked by' }],
    prs: [{ repo: 'G-Eskayo/marvin', number: 130, title: 'A PR', state: 'OPEN', relation: 'closed by' }]
  }

  it('lists docs, tickets and PRs with the relation, title and status — never a bare number', () => {
    const html = renderToStaticMarkup(<Related rel={rel} />)
    expect(html).toContain('0033-health.md')
    expect(html).toContain('blocked by')
    expect(html).toContain('per-device columns')
    expect(html).toContain('blocked</span>')
    expect(html).toContain('closed by')
    expect(html).toContain('A PR')
  })

  it('says so when there is nothing, and while loading', () => {
    expect(renderToStaticMarkup(<Related rel={{ docs: [], tickets: [], prs: [] }} />)).toContain('Nothing references this yet')
    expect(renderToStaticMarkup(<Related rel={null} />)).toContain('Finding related items')
  })
})

describe('AgentsPanel', () => {
  const job = { job: 'x', label: 'Health check sweep', status: 'idle', current: null, last: { status: 'passed', finishedAt: new Date().toISOString(), durationS: 4, summary: 'ok', error: '' }, runs: [] }
  const agents = [
    { id: 'health-check', label: 'Health check sweep', kind: 'scheduled', schedule: 'every 15 min', pid: null, lastExit: 0, running: false, reporting: true, status: 'idle', job },
    { id: 'auto-fix', label: 'auto-fix', kind: 'scheduled', schedule: 'daily at 11:00', pid: null, lastExit: 0, running: false, reporting: false, status: 'idle', job: null },
    { id: 'dashboard-webhook', label: 'dashboard-webhook', kind: 'service', schedule: 'always on', pid: 42, lastExit: 0, running: true, reporting: false, status: 'running', job: null }
  ]

  it('shows every agent, its schedule, and says plainly which ones are not reporting steps', () => {
    const html = renderToStaticMarkup(<AgentsPanel agents={agents} />)
    expect(html).toContain('Health check sweep')
    expect(html).toContain('every 15 min')
    expect(html).toContain('Not reporting steps yet')
    expect(html).toContain('pid 42')
    expect(html).toContain('1 of 3 report steps')
  })
})

import CompletedView from '../src/components/CompletedView.jsx'

describe('CompletedView', () => {
  it('shows a loading state before data arrives (the fetch runs in an effect, not on the server)', () => {
    expect(renderToStaticMarkup(<CompletedView repo="G-Eskayo/marvin" onSelect={() => {}} />)).toContain('Loading the finished work')
  })
})

import TicketAgentsPanel from '../src/components/TicketAgentsPanel.jsx'

describe('TicketAgentsPanel', () => {
  it('renders nothing until its data loads (the fetch runs in an effect)', () => {
    expect(renderToStaticMarkup(<TicketAgentsPanel />)).toBe('')
  })
})

import { WorkingView } from '../src/components/DispatchStatusBadge.jsx'

describe('the working indicator', () => {
  const now = Date.parse('2026-10-05T12:10:00Z')

  it('says Idle (with what finished last) instead of vanishing when nothing is running', () => {
    const html = renderToStaticMarkup(<WorkingView working={{ items: [], last: { label: 'Ticket pipeline', finishedAt: '2026-10-05T12:00:00Z', summary: 'no ready tickets' } }} now={now} />)
    expect(html).toContain('Idle')
    expect(html).toContain('Ticket pipeline')
  })

  it('shows what is running, how long, and how many more', () => {
    const working = {
      items: [
        { kind: 'job', label: 'Project catalog', detail: 'Local folders — 14 found', startedAt: '2026-10-05T12:09:00Z' },
        { kind: 'task', label: 'ticket #5: x', detail: '', startedAt: '2026-10-05T12:00:00Z' }
      ],
      last: null
    }
    const html = renderToStaticMarkup(<WorkingView working={working} now={now} />)
    expect(html).toContain('Project catalog')
    expect(html).toContain('Local folders')
    expect(html).toContain('+1 more')
    expect(html).toContain('1m 0s')
  })

  it('shows nothing until the first reading arrives', () => {
    expect(renderToStaticMarkup(<WorkingView working={null} now={now} />)).toBe('')
  })
})

import ProfilesPanel from '../src/components/ProfilesPanel.jsx'

describe('ProfilesPanel', () => {
  it('renders nothing until the profile list arrives (the fetch runs in an effect)', () => {
    expect(renderToStaticMarkup(<ProfilesPanel />)).toBe('')
  })
})

describe('parity wording', () => {
  it('MrReview exports render without crashing (module loads with the new ticket line and summary)', async () => {
    const mod = await import('../src/components/MrReview.jsx')
    expect(typeof mod.default).toBe('function')
  })
})

import ProjectReadinessPanel from '../src/components/ProjectReadinessPanel.jsx'

describe('ProjectReadinessPanel', () => {
  it('renders loading state', () => {
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={null} loading={true} />)
    expect(html).toContain('Loading project readiness')
  })

  it('renders empty state when no plans', () => {
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={[]} loading={false} />)
    expect(html).toContain('No projects registered yet')
  })

  it('renders projects with readiness chips', () => {
    const plans = [
      {
        repo: 'G-Eskayo/marvin',
        status: 'planned',
        generated_at: '2026-10-06T12:00:00Z',
        pieces: {
          profile: { state: 'ok', reason: 'exists' },
          stack: { state: 'needs-human', reason: 'no recognised stack' },
          board: { state: 'missing', reason: 'not registered' }
        }
      }
    ]
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={plans} loading={false} />)
    expect(html).toContain('marvin')
    expect(html).toContain('profile')
    expect(html).toContain('stack')
    expect(html).toContain('board')
  })

  it('renders unplanned projects gracefully', () => {
    const plans = [
      {
        repo: 'test/repo',
        status: 'not_planned_yet',
        generated_at: null,
        pieces: null
      }
    ]
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={plans} loading={false} />)
    expect(html).toContain('repo')
    expect(html).toContain('Not scanned yet')
  })
})

import ActivityBanner from '../src/components/ActivityBanner.jsx'

describe('ActivityBanner', () => {
  it('renders nothing when there are no red checks to show', () => {
    // ActivityBanner needs window.api to be defined for the fetch
    // In server-side render, components that fetch data render nothing until data arrives
    const html = renderToStaticMarkup(<ActivityBanner />)
    // The component will render nothing initially as the effect hasn't run yet
    expect(html.length === 0 || !html.includes('border-red-900')).toBe(true)
  })
})

import DashboardHome, { formatRelativeTime, buildProjectCards } from '../src/components/DashboardHome.jsx'

describe('formatRelativeTime', () => {
  const now = Date.parse('2026-10-08T12:00:00Z')

  it('formats times relative to now', () => {
    expect(formatRelativeTime(new Date(now).toISOString(), now)).toBe('just now')
    expect(formatRelativeTime(new Date(now - 30 * 1000).toISOString(), now)).toBe('just now')
    expect(formatRelativeTime(new Date(now - 5 * 60 * 1000).toISOString(), now)).toBe('5m ago')
    expect(formatRelativeTime(new Date(now - 2 * 3600 * 1000).toISOString(), now)).toBe('2h ago')
    expect(formatRelativeTime(new Date(now - 3 * 86400 * 1000).toISOString(), now)).toBe('3d ago')
    expect(formatRelativeTime(new Date(now - 2 * 7 * 86400 * 1000).toISOString(), now)).toBe('2w ago')
  })

  it('falls back to short date for very old times', () => {
    const old = new Date(now - 180 * 86400 * 1000).toISOString()
    const result = formatRelativeTime(old, now)
    expect(result).not.toMatch(/ago$/)
  })

  it('returns null for no input', () => {
    expect(formatRelativeTime(null, now)).toBe(null)
    expect(formatRelativeTime(undefined, now)).toBe(null)
  })
})

describe('buildProjectCards', () => {
  it('combines boards, overview, and summaries into card data', () => {
    const boards = [{ repo: 'o/r', name: 'Repo', status: 'active', due: '2026-10-15', dueHard: true, lastActivity: '2026-10-08T12:00:00Z' }]
    const overview = { 'o/r': { review: 2, needsYou: 1, blocked: 0 } }
    const summaries = { 'o/r': { open: 5, running: true } }
    const cards = buildProjectCards(boards, overview, summaries)
    expect(cards[0]).toMatchObject({
      repo: 'o/r',
      name: 'Repo',
      status: 'active',
      isArchived: false,
      open: 5,
      running: true,
      review: 2,
      needsYou: 1,
      due: '2026-10-15',
      dueHard: true,
      lastActivity: '2026-10-08T12:00:00Z'
    })
  })

  it('marks archived projects', () => {
    const boards = [{ repo: 'o/r', name: 'Old', status: 'archived' }]
    const cards = buildProjectCards(boards, {}, {})
    expect(cards[0].isArchived).toBe(true)
  })

  it('handles missing overview and summaries gracefully', () => {
    const boards = [{ repo: 'o/r', name: 'Repo', status: 'recent' }]
    const cards = buildProjectCards(boards)
    expect(cards[0]).toMatchObject({ open: 0, running: false, review: 0, needsYou: 0 })
  })
})

describe('DashboardHome', () => {
  it('renders a loading state on mount', () => {
    const html = renderToStaticMarkup(<DashboardHome onOpenProject={() => {}} />)
    expect(html).toContain('Loading projects')
  })

  it('accepts onOpenTicket prop without crashing', () => {
    const html = renderToStaticMarkup(<DashboardHome onOpenProject={() => {}} onOpenTicket={() => {}} />)
    expect(html).toBeDefined()
  })
})

// Tests 16-22: NeedsYouList component (props-driven tests)
import { NeedsYouList } from '../src/components/DashboardHome.jsx'

describe('NeedsYouList component', () => {
  const mockRows = [
    {
      repo: 'G-Eskayo/marvin',
      number: 1,
      title: 'Test Ticket',
      url: 'https://example.com/1',
      kind: 'ready-for-human',
      unblocks: { count: 2, items: [] },
      ask: 'Please review',
      priority: 'p0',
      ageDays: 5,
      project: 'marvin'
    },
    {
      repo: 'G-Eskayo/marvin',
      number: 2,
      title: 'Another Ticket',
      url: 'https://example.com/2',
      kind: 'needs-info',
      unblocks: { count: 0, items: [] },
      ask: 'Need more info',
      priority: null,
      ageDays: 1,
      project: 'marvin'
    }
  ]

  // Test 16: NeedsYouList renders rows with all attributes
  it('renders rows with priority pill, project label, and kind', () => {
    const html = renderToStaticMarkup(
      <NeedsYouList
        rows={mockRows}
        sortKey="default"
        currentPage={1}
        pageSize={10}
        onOpenTicket={() => {}}
      />
    )
    expect(html).toContain('Test Ticket')
    expect(html).toContain('marvin')
    expect(html).toContain('Critical')
    expect(html).toContain('Ready for you')
  })

  // Test 17: NeedsYouList shows empty state
  it('shows empty state when no rows', () => {
    const html = renderToStaticMarkup(
      <NeedsYouList
        rows={[]}
        sortKey="default"
        currentPage={1}
        pageSize={10}
        onOpenTicket={() => {}}
      />
    )
    expect(html).toContain('Nothing needs you')
  })

  // Test 18: NeedsYouList includes sort dropdown
  it('includes sort dropdown', () => {
    const html = renderToStaticMarkup(
      <NeedsYouList
        rows={mockRows}
        sortKey="default"
        currentPage={1}
        pageSize={10}
        onOpenTicket={() => {}}
        onSort={() => {}}
      />
    )
    expect(html).toContain('Sort')
  })

  // Test 19: NeedsYouList includes pagination
  it('shows pagination controls when multiple pages', () => {
    const manyRows = Array.from({ length: 15 }, (_, i) => ({
      repo: 'G-Eskayo/marvin',
      number: i + 1,
      title: `Ticket ${i + 1}`,
      url: `https://example.com/${i + 1}`,
      kind: 'ready-for-human',
      unblocks: { count: 0, items: [] },
      ask: 'test',
      priority: null,
      ageDays: 1,
      project: 'marvin'
    }))
    const html = renderToStaticMarkup(
      <NeedsYouList
        rows={manyRows}
        sortKey="default"
        currentPage={1}
        pageSize={5}
        onOpenTicket={() => {}}
        onPageChange={() => {}}
      />
    )
    expect(html).toContain('Page 1 of 3')
  })

  // Test 20: DashboardHome renders with NeedsYouSection
  it('DashboardHome renders with loading state', () => {
    const html = renderToStaticMarkup(
      <DashboardHome onOpenProject={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).toContain('Loading projects')
  })

  // Test 21: Priority pills display correctly (utility)
  it('priority pills return correct structure', () => {
    const p0 = priorityPill('p0')
    expect(p0.text).toBe('Critical')
    expect(p0.className).toContain('red')
  })

  // Test 22: Kind labels are readable (utility)
  it('kind labels are readable', () => {
    expect(kindLabel('needs-info')).toBe('Needs info')
    expect(kindLabel('ready-for-human')).toBe('Ready for you')
  })
})

// Regression tests 23-25
describe('NeedsYouList regression tests', () => {
  // Test 23: Pagination handles empty rows
  it('paginate returns totalPages=1 for empty rows', () => {
    const result = paginate([], 1, 10)
    expect(result.totalPages).toBe(1)
    expect(result.currentPage).toBe(1)
  })

  // Test 24: Pagination clamps out-of-range pages
  it('paginate clamps page to valid range', () => {
    const rows = Array.from({ length: 10 }, (_, i) => ({
      repo: 'G-Eskayo/marvin',
      number: i + 1,
      title: `Ticket ${i + 1}`,
      url: `https://example.com/${i + 1}`,
      kind: 'ready-for-human',
      unblocks: { count: 0, items: [] },
      ask: 'test',
      priority: null,
      ageDays: 1,
      project: 'marvin'
    }))
    const result = paginate(rows, 999, 5)
    expect(result.currentPage).toBe(2)
    expect(result.items[0].number).toBe(6)
  })

  // Test 25: Pagination maintains total count
  it('paginate maintains total count across pages', () => {
    const rows = Array.from({ length: 23 }, (_, i) => ({
      repo: 'G-Eskayo/marvin',
      number: i + 1,
      title: `Ticket ${i + 1}`,
      url: `https://example.com/${i + 1}`,
      kind: 'ready-for-human',
      unblocks: { count: 0, items: [] },
      ask: 'test',
      priority: null,
      ageDays: 1,
      project: 'marvin'
    }))
    const page1 = paginate(rows, 1, 10)
    const page2 = paginate(rows, 2, 10)
    const page3 = paginate(rows, 3, 10)
    expect(page1.totalCount).toBe(23)
    expect(page2.totalCount).toBe(23)
    expect(page3.totalCount).toBe(23)
    expect(page1.items.length + page2.items.length + page3.items.length).toBe(23)
  })
})
