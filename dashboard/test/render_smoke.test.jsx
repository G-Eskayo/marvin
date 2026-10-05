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
