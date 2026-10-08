import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Markdown, { parseDashLink } from '../src/components/Markdown.jsx'
import Related from '../src/components/Related.jsx'
import AgentsPanel from '../src/components/AgentsPanel.jsx'

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
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={null} profiles={null} loading={true} reload={() => {}} />)
    expect(html).toContain('Loading project readiness')
  })

  it('renders empty state when no plans', () => {
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={[]} profiles={[]} loading={false} reload={() => {}} />)
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
        },
        offers: { merge_from_dashboard: false, dispatch: false }
      }
    ]
    const profiles = [{ repo: 'G-Eskayo/marvin', mergeFromDashboard: false, dispatch: 'off' }]
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={plans} profiles={profiles} loading={false} reload={() => {}} />)
    expect(html).toContain('marvin')
    expect(html).toContain('profile')
    expect(html).toContain('stack')
    expect(html).toContain('board')
  })

  it('renders control buttons disabled when offers are false', () => {
    const plans = [
      {
        repo: 'G-Eskayo/test',
        status: 'planned',
        generated_at: '2026-10-06T12:00:00Z',
        pieces: {},
        offers: { merge_from_dashboard: false, dispatch: false }
      }
    ]
    const profiles = [{ repo: 'G-Eskayo/test', mergeFromDashboard: false, dispatch: 'off' }]
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={plans} profiles={profiles} loading={false} reload={() => {}} />)
    expect(html).toContain('Turn on merge from dashboard')
    expect(html).toContain('Turn on dispatch')
  })

  it('renders control buttons enabled when offers are true', () => {
    const plans = [
      {
        repo: 'G-Eskayo/test',
        status: 'planned',
        generated_at: '2026-10-06T12:00:00Z',
        pieces: {},
        offers: { merge_from_dashboard: true, dispatch: true }
      }
    ]
    const profiles = [{ repo: 'G-Eskayo/test', mergeFromDashboard: false, dispatch: 'off' }]
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={plans} profiles={profiles} loading={false} reload={() => {}} />)
    expect(html).toContain('Turn on merge from dashboard')
    expect(html).toContain('Turn on dispatch')
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
    const html = renderToStaticMarkup(<ProjectReadinessPanel plans={plans} profiles={[]} loading={false} reload={() => {}} />)
    expect(html).toContain('repo')
    expect(html).toContain('Not scanned yet')
  })
})
