import { describe, it, expect } from 'vitest'
import { verdictLine } from '../src/lib/verdict_line.js'

const NOW = new Date('2026-10-14T17:00:00Z').getTime()

describe('verdictLine: Health tab verdict rendering', () => {
  it('shows UNKNOWN when overall is null or missing', () => {
    expect(verdictLine({ overall: null, checksCount: 5, copy: {} }, NOW)).toEqual({ tone: 'unknown', text: 'HEALTH UNKNOWN' })
    expect(verdictLine({ overall: undefined, checksCount: 5, copy: {} }, NOW)).toEqual({ tone: 'unknown', text: 'HEALTH UNKNOWN' })
  })

  it('shows UNKNOWN when no checks exist', () => {
    expect(verdictLine({ overall: 'green', checksCount: 0, copy: {} }, NOW)).toEqual({ tone: 'unknown', text: 'HEALTH UNKNOWN' })
  })

  it('shows UNKNOWN when overall has an unrecognized severity', () => {
    expect(verdictLine({ overall: 'purple', checksCount: 5, copy: {} }, NOW)).toEqual({ tone: 'unknown', text: 'HEALTH UNCONFIRMED' })
    expect(verdictLine({ overall: 'grey', checksCount: 5, copy: {} }, NOW)).toEqual({ tone: 'unknown', text: 'HEALTH UNCONFIRMED' })
  })

  it('shows HEALTHY when overall is green and not stale', () => {
    const result = verdictLine({ overall: 'green', checksCount: 5, generatedAt: new Date(NOW), copy: { ageS: 300 } }, NOW)
    expect(result.tone).toBe('nominal')
    expect(result.text).toMatch(/^HEALTHY · .* AGO$/)
  })

  it('shows DEGRADED when overall is yellow', () => {
    expect(verdictLine({ overall: 'yellow', checksCount: 5, copy: {} }, NOW)).toEqual({ tone: 'issues', text: 'DEGRADED' })
  })

  it('shows CRITICAL when overall is red', () => {
    expect(verdictLine({ overall: 'red', checksCount: 5, copy: {} }, NOW)).toEqual({ tone: 'issues', text: 'CRITICAL' })
  })

  it('shows SWEEP FROZEN when stale snapshot with valid age', () => {
    const result = verdictLine(
      { overall: 'green', checksCount: 5, generatedAt: new Date(NOW), copy: { ageS: 1200, stale: true } },
      NOW
    )
    expect(result.tone).toBe('stale')
    expect(result.text).toMatch(/^SWEEP FROZEN · 20 MIN AGO$/)
  })

  it('shows FUTURE-DATED SNAPSHOT when snapshot is from the future', () => {
    const result = verdictLine(
      { overall: 'green', checksCount: 5, generatedAt: new Date(NOW), copy: { ageS: 0, future: true } },
      NOW
    )
    expect(result.tone).toBe('stale')
    expect(result.text).toMatch(/^FUTURE-DATED SNAPSHOT · /)
  })

  it('renders HEALTHY without age when generatedAt is missing but not stale', () => {
    const result = verdictLine({ overall: 'green', checksCount: 5, copy: {} }, NOW)
    expect(result.tone).toBe('nominal')
    expect(result.text).toBe('HEALTHY')
  })

  it('handles stale yellow/red checks (stale state takes precedence)', () => {
    const result = verdictLine(
      { overall: 'yellow', checksCount: 5, generatedAt: new Date(NOW), copy: { ageS: 1200, stale: true } },
      NOW
    )
    expect(result.tone).toBe('stale')
    expect(result.text).toMatch(/^SWEEP FROZEN · 20 MIN AGO$/)
  })
})
