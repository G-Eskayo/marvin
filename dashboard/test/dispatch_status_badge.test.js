import { describe, it, expect } from 'vitest'
import { formatElapsed } from '../src/components/DispatchStatusBadge.jsx'

describe('formatElapsed', () => {
  it('shows just seconds under a minute', () => {
    const start = new Date('2026-08-31T20:00:00Z')
    const now = new Date('2026-08-31T20:00:42Z').getTime()
    expect(formatElapsed(start.toISOString(), now)).toBe('42s')
  })

  it('shows minutes and seconds once a minute has passed', () => {
    const start = new Date('2026-08-31T20:00:00Z')
    const now = new Date('2026-08-31T20:04:12Z').getTime()
    expect(formatElapsed(start.toISOString(), now)).toBe('4m 12s')
  })

  it('never goes negative for a clock skew edge case', () => {
    const start = new Date('2026-08-31T20:00:05Z')
    const now = new Date('2026-08-31T20:00:00Z').getTime()
    expect(formatElapsed(start.toISOString(), now)).toBe('0s')
  })

  it('returns null for an unparseable startedAt', () => {
    expect(formatElapsed('not-a-date', Date.now())).toBeNull()
  })
})
