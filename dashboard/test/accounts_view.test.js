import { describe, it, expect } from 'vitest'
import { accountsSummary, expiryText, daysLeft } from '../src/lib/accounts_view.js'

const NOW = Date.parse('2026-10-30T12:00:00Z')
const r = (id, machine, state, extra = {}) => ({ id, machine, state, label: id, ...extra })

describe('accountsSummary', () => {
  it('worst first, this machine first, not-needed folded away, headline counts', () => {
    const rows = [r('tailscale', 'mac-mini-2012', 'works'), r('github-token', 'mac-mini-2012', 'not_needed'), r('claude-login', 'mac-mini-2012', 'expiring'),
      r('github-token', 'mac-mini-1', 'works'), r('gh-login', 'mac-mini-1', 'failed'), r('x', 'macbook-pro-1', 'unreachable')]
    const s = accountsSummary(rows, { thisMachine: 'mac-mini-1' })
    expect(s.groups.map((g) => g.machine)).toEqual(['mac-mini-1', 'mac-mini-2012', 'macbook-pro-1'])
    expect(s.groups[0].rows.map((x) => x.state)).toEqual(['failed', 'works'])
    expect(s.groups[1].hidden).toBe(1)
    expect(s.headline).toBe('1 needs renewing')
    expect(s.severity).toBe('red')
  })
  it('empty, garbage and all-good inputs', () => {
    expect(accountsSummary(null).headline).toBe('All signed in')
    expect(accountsSummary([null, 5, { id: 1 }]).groups).toEqual([])
    expect(accountsSummary([r('a', 'm', 'expiring'), r('b', 'm', 'expiring')]).headline).toBe('2 run out soon')
  })
})

describe('expiryText', () => {
  it('days left, estimated, past, missing, junk', () => {
    expect(expiryText({ expires_at: '2026-11-13T07:06:00+00:00', state: 'expiring' }, NOW)).toBe('13 days left (2026-11-13)')
    expect(expiryText({ expires_at: '2027-07-13T00:00:00+00:00', estimated: true, state: 'works' }, NOW)).toMatch(/left \(about 2027-07-13\)/)
    expect(expiryText({ expires_at: '2026-10-01T00:00:00+00:00', state: 'failed' }, NOW)).toBe('expired 2026-10-01')
    expect(expiryText({ state: 'works' }, NOW)).toBe('no expiry date')
    expect(daysLeft('soon', NOW)).toBeNull()
  })
})

// The Vitals Accounts card (marvin#873, owner 2026-11-11): the redesign's view. Keeps #974's answers: every account on
// every machine grouped by machine, "not needed here" folded into a count, gh's own login shown but never alerting,
// amber 14 days before expiry. Health's card (accountsSummary above) is frozen and unchanged.
import { accountsBoard } from '../src/lib/accounts_view.js'

describe('accountsBoard', () => {
  const day = 86_400_000
  const inDays = (d) => new Date(NOW + d * day).toISOString()
  it("gh's own login is shown but never alerts: it doesn't set the card's colour or headline", () => {
    const b = accountsBoard([r('gh-login', 'macbook-pro-1', 'failed', { alert: false }), r('github-token', 'macbook-pro-1', 'works')], { thisMachine: 'macbook-pro-1', now: NOW })
    expect(b.headline).toBe('All signed in')
    expect(b.severity).toBe('green')
    const gh = b.groups[0].rows.find((x) => x.id === 'gh-login')
    expect(gh.quiet).toBe(true)
    expect(gh.state).toBe('failed')
    expect(b.quiet).toBe(1)
  })
  it('amber 14 days before a known expiry, even when the backend still says works', () => {
    const b = accountsBoard([r('a', 'm', 'works', { expires_at: inDays(10) }), r('b', 'm', 'works', { expires_at: inDays(20) })], { now: NOW })
    expect(b.groups[0].rows.map((x) => [x.id, x.state])).toEqual([['a', 'expiring'], ['b', 'works']])
    expect(b.groups[0].rows[0].daysLeft).toBe(10)
    expect(b.headline).toBe('1 runs out soon')
    expect(b.severity).toBe('yellow')
  })
  it('grouped by machine, this machine first, not-needed folded into a count, worst first inside', () => {
    const rows = [r('t', 'mac-mini-2012', 'works'), r('x', 'mac-mini-2012', 'not_needed'), r('y', 'mac-mini-2012', 'not_needed'),
      r('g', 'mac-mini-1', 'works'), r('k', 'mac-mini-1', 'failed'), r('c', 'macbook-pro-1', 'works')]
    const b = accountsBoard(rows, { thisMachine: 'macbook-pro-1', now: NOW })
    expect(b.groups.map((g) => g.machine)).toEqual(['macbook-pro-1', 'mac-mini-1', 'mac-mini-2012'])
    expect(b.groups[1].rows.map((x) => x.id)).toEqual(['k', 'g'])
    expect(b.groups[2].hidden).toBe(2)
    expect(b.groups[2].rows.map((x) => x.id)).toEqual(['t'])
    expect(b.headline).toBe('1 needs renewing')
    expect(b.counts).toMatchObject({ shown: 4, failed: 1, expiring: 0 })
  })
  it('junk and empty input', () => {
    expect(accountsBoard(null).groups).toEqual([])
    expect(accountsBoard([null, 3, { id: 2 }]).headline).toBe('All signed in')
    expect(accountsBoard([r('a', 'm', 'works', { expires_at: 'soon' })], { now: NOW }).groups[0].rows[0].daysLeft).toBe(null)
  })
})
