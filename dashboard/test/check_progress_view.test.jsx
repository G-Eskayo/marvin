import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CheckProgress from '../src/components/CheckProgress.jsx'

// marvin#555: the approved look (Gil, 2026-10-21). Collapsed: bar, "N of M done", what's running, when last checked.
// Expanded: one row per check.
const NOW = Date.parse('2026-10-21T06:02:07Z')
const runs = [
  { name: 'Website checks', status: 'passed', done: true, startedAt: '2026-10-21T05:58:02Z', completedAt: '2026-10-21T05:58:50Z' },
  { name: 'CaptionCore unit tests', status: 'passed', done: true, startedAt: '2026-10-21T05:58:03Z', completedAt: '2026-10-21T06:01:15Z' },
  { name: 'App builds (iOS)', status: 'running', done: false, startedAt: '2026-10-21T05:58:02Z', completedAt: null }
]
const checks = { state: 'pending', failing: [], pending: ['App builds (iOS)'], runs, checkedAt: NOW - 20_000 }
const html = (props) => renderToStaticMarkup(<CheckProgress checks={checks} now={NOW} {...props} />)
const text = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

describe('CheckProgress', () => {
  it('collapsed (the default): the bar filled 2/3, the count, what is running and when GitHub was last asked', () => {
    const h = html()
    expect(h).toContain('aria-expanded="false"')
    expect(h).toMatch(/style="width:67%"/)
    expect(text(h)).toContain('2 of 3 done')
    expect(text(h)).toContain('Still running: App builds (iOS) · 4:05')
    expect(text(h)).toContain('Last checked 20 s ago')
    expect(h).not.toContain('data-check-row')
  })

  it('expanded: one row per check, finished ones with their duration, the running one with time so far', () => {
    const h = html({ defaultOpen: true })
    expect(h).toContain('aria-expanded="true"')
    const rows = h.match(/data-check-row="[^"]*"/g)
    expect(rows).toEqual(['data-check-row="passed"', 'data-check-row="passed"', 'data-check-row="running"'])
    expect(text(h)).toMatch(/✓ Website checks passed 0:48/)
    expect(text(h)).toMatch(/✓ CaptionCore unit tests passed 3:12/)
    expect(text(h)).toMatch(/◌ App builds \(iOS\) running 4:05/)
  })

  it('a failed check is marked ✗ in the rows; nothing running means no "Still running" line', () => {
    const failed = { ...checks, state: 'failing', runs: [{ ...runs[0], status: 'failed' }] }
    const h = renderToStaticMarkup(<CheckProgress checks={failed} now={NOW} defaultOpen />)
    expect(text(h)).toMatch(/✗ Website checks failed 0:48/)
    expect(h).not.toContain('Still running')
    expect(text(h)).toContain('1 of 1 done')
  })

  it('no checks: renders nothing at all', () => {
    expect(renderToStaticMarkup(<CheckProgress checks={{ state: 'none', runs: [] }} now={NOW} />)).toBe('')
    expect(renderToStaticMarkup(<CheckProgress checks={null} now={NOW} />)).toBe('')
  })

  it('unknown last-checked time: the line is left out rather than guessed', () => {
    expect(renderToStaticMarkup(<CheckProgress checks={{ ...checks, checkedAt: null }} now={NOW} />)).not.toContain('Last checked')
  })

  it('a very long check name is truncated on screen but kept whole in its tooltip', () => {
    const long = 'Build and test every target on every simulator we own including the very slow ones'.repeat(2)
    const h = renderToStaticMarkup(<CheckProgress checks={{ ...checks, runs: [{ ...runs[2], name: long }] }} now={NOW} defaultOpen />)
    expect(h).toContain(`title="${long}"`)
    expect(h).toMatch(/class="[^"]*truncate/)
  })

  it('the time comes from the clock it is given, so it moves without asking GitHub', () => {
    const later = renderToStaticMarkup(<CheckProgress checks={checks} now={NOW + 5000} />)
    expect(text(later)).toContain('App builds (iOS) · 4:10')
    expect(text(later)).toContain('Last checked 25 s ago')
  })

  it('12 checks: the running line stays one short line', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ name: `job ${i}`, status: 'running', done: false, startedAt: '2026-10-21T06:02:00Z', completedAt: null }))
    const h = renderToStaticMarkup(<CheckProgress checks={{ ...checks, runs: many }} now={NOW} />)
    expect(text(h)).toContain('Still running: job 0 · 0:07, job 1 · 0:07 and 10 more')
    expect(text(h)).toContain('0 of 12 done')
  })
})
