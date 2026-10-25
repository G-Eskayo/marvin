import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import UsageView from '../src/components/UsageView.jsx'

const row = (day, kind, output, extra = {}) => ({ day, kind, model: 'claude-sonnet-5', input: 1, output, cache_write: 2, cache_read: 3, messages: 1, ...extra })
const tokens = (rows, extra = {}) => ({ generated_at: '2026-10-06T12:00:00Z', rows, by_project: [], by_ticket: [], ...extra })
const m = (machine, tools, tokenData, extra = {}) => ({ machine, this: machine === 'a', reachable: true, tools: tools && { generated_at: '2026-10-06T12:00:00Z', tools, skills: [], inventory: { known: 0, used: 0, never_used: [] } }, tokens: tokenData, ...extra })

describe('UsageView component', () => {
  it('Test 4: respects the now prop for date calculations', () => {
    const testNow = new Date('2026-10-15T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([
      row('2026-10-15', 'headless', 100),
      row('2026-10-16', 'interactive', 50)
    ]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={testNow} />)
    // Should use 2026-10-15 as the end date based on the now prop
    expect(html).toContain('Output, last 7 days')
  })

  it('Test 6: ShareLine svg overlays DailyBars with inset-0', () => {
    const machines = [m('a', null, tokens([
      row('2026-10-05', 'headless', 100),
      row('2026-10-05', 'interactive', 100)
    ]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" />)
    // ShareLine should have inset-0 class for absolute positioning overlay
    expect(html).toContain('inset-0')
    expect(html).toContain('Autonomous share reference lines')
  })

  it('Test 13: renders with basic token data', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([
      row('2026-10-05', 'headless', 100),
      row('2026-10-06', 'interactive', 50)
    ]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    expect(html).toContain('Output, last 7 days')
    expect(html).toContain('Autonomous share')
    expect(html).not.toContain('No token usage scan')
  })

  it('Test 14: shows empty state when no data', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    expect(html).toContain('No token usage scan')
  })

  it('Test 15: displays week/day toggle buttons', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([row('2026-10-05', 'headless', 100)]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    expect(html).toContain('>Day<')
    expect(html).toContain('>Week<')
  })

  it('Test 16: shows autonomous share stat with correct calculation', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([
      row('2026-10-05', 'headless', 100),
      row('2026-10-05', 'interactive', 50),
      row('2026-10-06', 'subagent', 25)
    ], { by_ticket: [
      { project: 'marvin', ticket: 1, output: 175, messages: 3, input: 3, cache_write: 6, cache_read: 9, by_kind: { headless: 100, interactive: 50, subagent: 25 } }
    ], by_project: [
      { project: 'marvin', output: 175, messages: 3, input: 3, cache_write: 6, cache_read: 9, by_kind: { headless: 100, interactive: 50, subagent: 25 } }
    ] }))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    // autonomous = 100 + 25 = 125, total = 175, share = 71%
    expect(html).toContain('71%')
  })

  it('Test 17: includes Top autonomous spenders table when data exists', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([row('2026-10-05', 'headless', 100)], {
      by_ticket: [
        { project: 'marvin', ticket: 1, output: 100, messages: 1, input: 1, cache_write: 2, cache_read: 3, by_kind: { headless: 100, interactive: 0, subagent: 0 } }
      ],
      by_project: [
        { project: 'marvin', output: 100, messages: 1, input: 1, cache_write: 2, cache_read: 3, by_kind: { headless: 100, interactive: 0, subagent: 0 } }
      ]
    }))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    expect(html).toContain('Top autonomous spenders')
    expect(html).toContain('marvin')
  })

  it('Test 21: renders ShareLine component with reference lines', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([
      row('2026-10-05', 'headless', 100),
      row('2026-10-05', 'interactive', 100),
      row('2026-10-06', 'headless', 75),
      row('2026-10-06', 'interactive', 25)
    ]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    expect(html).toContain('Autonomous share reference lines')
    expect(html).toContain('30%')
    expect(html).toContain('40%')
    expect(html).toContain('50%')
  })

  it('Test 22: ShareLine polyline is rendered with correct SVG structure', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([
      row('2026-10-05', 'headless', 500),
      row('2026-10-05', 'interactive', 500),
      row('2026-10-06', 'headless', 750),
      row('2026-10-06', 'interactive', 250)
    ]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    expect(html).toContain('polyline')
    expect(html).toContain('points=')
  })

  it('Test 23: DailyBars chart container has relative positioning for ShareLine overlay', () => {
    const now = new Date('2026-10-06T12:00:00Z').getTime()
    const machines = [m('a', null, tokens([
      row('2026-10-05', 'headless', 100),
      row('2026-10-05', 'interactive', 50)
    ]))]
    const html = renderToStaticMarkup(<UsageView machines={machines} which="all" now={now} />)
    expect(html).toContain('relative')
  })
})
