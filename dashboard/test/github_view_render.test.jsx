import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import GithubView, { LowPointBars, CallBars } from '../src/components/GithubView.jsx'

// marvin#417: the sawtooth line is gone; one low-point bar per hour sits above calls per hour on the same columns.
const G0 = { dashboard: 0, pipeline: 0, tests: 0, health: 0, people: 0, other: 0 }
const slot = (i, total, budgetMin) => ({ key: `k${i}`, label: `${i}:00`, total, refused: 0, deferred: 0, groups: { ...G0, pipeline: total }, budgetMin, readings: budgetMin == null ? 0 : 1, callers: [] })
const noop = () => {}

describe('LowPointBars', () => {
  const html = renderToStaticMarkup(<LowPointBars slots={[slot(0, 1, 0.8), slot(1, 1, 0.3), slot(2, 1, 0.1), slot(3, 1, 0), slot(4, 0, null)]} active={null} onHover={noop} onPick={noop} />)
  it('colours each hour by how low it got', () => {
    expect(html).toContain('data-tone="green"')
    expect(html).toContain('data-tone="amber"')
    expect(html).toContain('data-tone="red"')
  })
  it('marks an hour that ran out, and leaves a gap where there was no reading', () => {
    expect((html.match(/data-out="1"/g) || []).length).toBe(1)
    expect((html.match(/data-gap="1"/g) || []).length).toBe(1)
  })
  it('the 20% floor line is drawn over the bars, so a bar can never hide it', () => {
    expect(html.indexOf('data-floor="1"')).toBeGreaterThan(html.lastIndexOf('data-tone='))
  })
  it('draws no line path (the sawtooth is gone)', () => {
    expect(html).not.toContain('<path')
  })
  it('has one hover/click column per hour', () => {
    expect((html.match(/fill="transparent"/g) || []).length).toBe(5)
  })
})

describe('CallBars', () => {
  it('shares the same columns as the bars above, and highlights the active hour', () => {
    const slots = [slot(0, 3, 0.5), slot(1, 0, null), slot(2, 9, 0.2)]
    const html = renderToStaticMarkup(<CallBars slots={slots} active={2} onHover={noop} onPick={noop} />)
    expect((html.match(/fill="transparent"/g) || []).length).toBe(3)
    expect(html).toContain('opacity="0.08"')
    expect(html).not.toContain('busiest bar')  // the label moved off the plot so it never covers a bar
  })
})

describe('GithubView', () => {
  const hours = Array.from({ length: 30 }, (_, i) => ({
    hour: `2026-10-${String(12 + Math.floor(i / 24)).padStart(2, '0')}T${String(i % 24).padStart(2, '0')}:00Z`,
    total: i, refused: 0, deferred: 0, groups: { ...G0, tests: i }, budget_min: i % 5 ? 0.6 : null, budget_readings: 1,
    callers: [{ caller: 'pytest', group: 'tests', calls: i }]
  }))
  const machines = [{ machine: 'mac-mini-1', github: { hours, top: [], latest_budget: { at: 1, graphql: 0.42 } } }]
  const html = renderToStaticMarkup(<GithubView machines={machines} which="all" />)
  it('shows the range buttons with 24h chosen by default', () => {
    expect(html).toMatch(/aria-pressed="true"[^>]*>24h</)
    expect(html).toMatch(/aria-pressed="false"[^>]*>30d</)
    expect(html).toContain('>7d<')
    expect(html).toContain('>30d<')
  })
  it('shows the latest allowance tile from latest_budget', () => {
    expect(html).toContain('42%')
  })
  it('shows the last hour in the detail line until something is pointed at', () => {
    expect(html).toMatch(/low 60% · 29 calls/)
    expect(html).toContain('tallest bar: 29 calls')
  })
  it('empty logs show the empty message, not a crash', () => {
    expect(renderToStaticMarkup(<GithubView machines={[]} which="all" />)).toContain('No GitHub calls logged')
  })
})
