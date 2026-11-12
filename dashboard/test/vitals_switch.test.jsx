import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { visibleTabs } from '../src/lib/tabs.js'
import { readVitalsSwitch, writeVitalsSwitch, VITALS_SWITCH_KEY } from '../src/lib/tabs.js'
import { VitalsView } from '../src/components/VitalsMockup.jsx'

// Vitals mock-up (marvin#873): behind a switch, and no tab is removed.
describe('the switch', () => {
  it('off: today\'s tabs exactly; on: the mock-up tab is added before Health, nothing removed', () => {
    const off = visibleTabs(null).map((t) => t.id)
    expect(off).not.toContain('vitals')
    const on = visibleTabs(null, { vitals: true }).map((t) => t.id)
    expect(on.filter((id) => id !== 'vitals')).toEqual(off)
    expect(on.indexOf('vitals')).toBe(on.indexOf('health') - 1)
    expect(visibleTabs('helper', { vitals: true }).map((t) => t.id)).toContain('support')
  })
  const mem = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), m } }
  it('remembered per Mac; off by default; storage that throws or is missing reads as off', () => {
    const s = mem()
    expect(readVitalsSwitch(s)).toBe(false)
    writeVitalsSwitch(s, true)
    expect(s.m.get(VITALS_SWITCH_KEY)).toBe('on')
    expect(readVitalsSwitch(s)).toBe(true)
    writeVitalsSwitch(s, false)
    expect(readVitalsSwitch(s)).toBe(false)
    expect(readVitalsSwitch(null)).toBe(false)
    expect(readVitalsSwitch({ getItem: () => { throw new Error('denied') } })).toBe(false)
    expect(() => writeVitalsSwitch({ setItem: () => { throw new Error('full') } }, true)).not.toThrow()
  })
})

// The view, rendered on real-shaped data (the ticket's break-it list).
const NOW = Date.parse('2026-11-12T17:00:00Z')
const iso = (m) => new Date(NOW - m * 60_000).toISOString()
const check = (id, severity, detail, extra = {}) => ({ id, label: id, severity, detail, checked_at: iso(2), ...extra })
const fresh = { host: 'mac-mini-1', ageS: 60, stale: false }
const render = (data, placement = 'overlay') => renderToStaticMarkup(<VitalsView data={{ loops: { loops: [] }, decisions: [], accounts: null, plan: null, ...data }} now={NOW} placement={placement} />)

describe('VitalsView', () => {
  it('0 items needing Gil: only the verdict line over the map, no column', () => {
    const html = render({ health: { checks: [check('a', 'green', 'ok')], copy: fresh } })
    expect(html).toContain('data-verdict="healthy"')
    expect(html).toContain('Healthy')
    expect(html).not.toContain('data-column')
  })
  it('60 items: the column shows 12, worst first, and offers the rest', () => {
    const checks = Array.from({ length: 60 }, (_, i) => check(`disk:space@m${i}`, 'red', `low ${i}`, { checked_at: iso(i) }))
    const html = render({ health: { checks, copy: fresh } })
    expect(html).toContain('60 things need you')
    expect((html.match(/data-row="/g) || []).length).toBe(12)
    expect(html).toContain('Show all 60 (48 more)')
    // the oldest first
    expect(html.indexOf('disk:space@m59')).toBeLessThan(html.indexOf('disk:space@m58'))
  })
  it('a row whose part is not on the map says so', () => {
    const html = render({ health: { checks: [check('errors@mac-mini-1', 'red', '8 kinds of error')], copy: fresh } })
    expect(html).toContain('not on the map yet')
  })
  it('the map not loaded yet: the column still works', () => {
    const html = render({ health: { checks: [check('disk:space@mac-mini-1', 'red', 'low -- check the sweep')], copy: fresh } })
    expect(html).toContain('Loading the live map')
    expect(html).toContain('data-row="check:disk:space@mac-mini-1"')
    expect(html).toContain('By hand:')
  })
  it('both placements render the same rows', () => {
    const health = { checks: [check('main:green', 'red', 'main fails')], copy: fresh }
    for (const p of ['overlay', 'below']) {
      const html = render({ health }, p)
      expect(html).toContain(`data-placement="${p}"`)
      expect(html).toContain('data-row="check:main:green"')
    }
  })
  it('a stale reading is never Healthy', () => {
    const html = render({ health: { checks: [], copy: { host: 'macbook-pro-1', ageS: 14 * 86400, stale: true } } })
    expect(html).toContain('No fresh reading')
    expect(html).toContain('(old)')
  })
  it('no budget reading: Flow says not enough data, never 0%', () => {
    const html = render({ health: { checks: [], copy: fresh } })
    expect(html).toContain('data-flow="none"')
    expect(html).not.toMatch(/Weekly 0%|5-hour 0%/)
  })
  it('the Accounts card: gh\'s own login shows, not alerting, and the card stays green', () => {
    const accounts = { accounts: [{ id: 'gh-login', machine: 'macbook-pro-1', label: "gh's own login", state: 'failed', alert: false, detail: 'invalid' }, { id: 'tailscale', machine: 'macbook-pro-1', label: 'Tailscale', state: 'works', expires_at: '2027-03-29T00:00:00Z' }], thisMachine: 'macbook-pro-1' }
    const html = render({ health: { checks: [], copy: fresh }, accounts })
    expect(html).toContain('All signed in')
    expect(html).toContain('not alerting')
    expect(html).toContain('data-quiet="1"')
  })
})
