import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import UsageView from '../src/components/UsageView.jsx'

const machine = (machine = 'mini', rows = [], jobs = []) => ({
  machine,
  reachable: true,
  tokens: {
    generated_at: '2026-10-06T12:00:00Z',
    rows,
    by_project: [],
    by_ticket: [],
    by_job: jobs,
  },
  tools: null,
})

describe('UsageView render', () => {
  it('renders autonomous/interactive share bars', () => {
    const rows = [
      { day: '2026-10-06', kind: 'headless', model: 'claude-sonnet-5', autonomous: 'autonomous', input: 100, output: 200, cache_write: 0, cache_read: 0, messages: 1 },
      { day: '2026-10-06', kind: 'interactive', model: 'claude-sonnet-5', autonomous: 'interactive', input: 50, output: 300, cache_write: 0, cache_read: 0, messages: 1 },
    ]
    const html = renderToStaticMarkup(<UsageView machines={[machine('mini', rows)]} which="all" />)
    expect(html).toContain('Autonomous vs interactive share')
  })

  it('renders job names in the autonomous spenders table', () => {
    const rows = [
      { day: '2026-10-06', kind: 'headless', model: 'claude-sonnet-5', autonomous: 'autonomous', input: 100, output: 200, cache_write: 0, cache_read: 0, messages: 1 },
    ]
    const jobs = [
      { job: 'daily-digest', input: 10, output: 500, cache_write: 0, cache_read: 0, messages: 5 },
      { job: 'auto-fix', input: 5, output: 100, cache_write: 0, cache_read: 0, messages: 2 },
    ]
    const html = renderToStaticMarkup(<UsageView machines={[machine('mini', rows, jobs)]} which="all" />)
    expect(html).toContain('daily-digest')
    expect(html).toContain('auto-fix')
  })

  it('shows empty state when there are no autonomous jobs', () => {
    const rows = [
      { day: '2026-10-06', kind: 'headless', model: 'claude-sonnet-5', autonomous: 'autonomous', input: 100, output: 200, cache_write: 0, cache_read: 0, messages: 1 },
    ]
    const html = renderToStaticMarkup(<UsageView machines={[machine('mini', rows, [])]} which="all" />)
    expect(html).toContain('No autonomous jobs in this window')
  })

  it('shows empty state when there is no data', () => {
    const html = renderToStaticMarkup(<UsageView machines={[]} which="all" />)
    expect(html).toContain('No token usage scan')
  })

  it('renders both per-day and per-week share bars', () => {
    const rows = Array.from({ length: 30 }, (_, i) => ({
      day: `2026-09-${String(i + 1).padStart(2, '0')}`,
      kind: i % 2 === 0 ? 'headless' : 'interactive',
      model: 'claude-sonnet-5',
      autonomous: i % 3 === 0 ? 'autonomous' : 'interactive',
      input: 10,
      output: 100,
      cache_write: 0,
      cache_read: 0,
      messages: 1,
    }))
    const html = renderToStaticMarkup(<UsageView machines={[machine('mini', rows)]} which="all" />)
    // Should have sections for per-day and per-week
    expect(html).toContain('Per day')
    expect(html).toContain('Per week')
  })

  it('renders all reference line percentage labels for autonomous/interactive share', () => {
    const rows = [
      { day: '2026-10-06', kind: 'headless', model: 'claude-sonnet-5', autonomous: 'interactive', input: 100, output: 200, cache_write: 0, cache_read: 0, messages: 1 },
    ]
    const html = renderToStaticMarkup(<UsageView machines={[machine('mini', rows)]} which="all" />)
    expect(html).toContain('30%')
    expect(html).toContain('40%')
    expect(html).toContain('50%')
  })

  it('renders share bar with 100% autonomous share', () => {
    const rows = [
      { day: '2026-10-06', kind: 'headless', model: 'claude-sonnet-5', autonomous: 'autonomous', input: 100, output: 200, cache_write: 0, cache_read: 0, messages: 1 },
      { day: '2026-10-07', kind: 'headless', model: 'claude-sonnet-5', autonomous: 'autonomous', input: 50, output: 100, cache_write: 0, cache_read: 0, messages: 1 },
    ]
    const html = renderToStaticMarkup(<UsageView machines={[machine('mini', rows)]} which="all" />)
    expect(html).toContain('100% autonomous')
  })
})
