import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import UsageView, { ShareLine, DailyBars } from '../src/components/UsageView.jsx'

describe('UsageView render tests (tests 11-13)', () => {
  it('Test 11: ShareLine renders SVG with correct percentage text', () => {
    const html = renderToStaticMarkup(<ShareLine share={0.35} />)
    expect(html).toContain('svg')
    expect(html).toContain('35%')
    expect(html).toContain('rect')
    expect(html).toContain('Autonomous spending')
  })

  it('Test 12: DailyBars renders bars for each data point in series', () => {
    const series = [
      { day: '2026-10-01', interactive: 10, headless: 20, subagent: 5, total: 35 },
      { day: '2026-10-02', interactive: 15, headless: 25, subagent: 8, total: 48 },
      { day: '2026-10-03', interactive: 0, headless: 0, subagent: 0, total: 0 }
    ]
    const html = renderToStaticMarkup(<DailyBars series={series} metric="output" bucketKey="day" />)
    expect(html).toContain('svg')
    expect(html).toContain('rect')
    expect((html.match(/rect/g) || []).length).toBeGreaterThan(0)
    expect(html).toContain('peak')
  })

  it('Test 13: UsageView renders empty state when no rows provided', () => {
    const machines = [{ machine: 'test', tokens: { rows: [], by_project: [], by_ticket: [], generated_at: '2026-10-06T12:00:00Z' } }]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="test" />)
    expect(html).toContain('No token usage scan')
    expect(html).not.toContain('Top autonomous spenders')
  })
})
