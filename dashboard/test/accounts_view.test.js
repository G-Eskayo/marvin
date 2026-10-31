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
