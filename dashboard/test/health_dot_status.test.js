import { describe, it, expect } from 'vitest'
import { healthDotStatus } from '../src/lib/health_dot_status.js'

const NOW = new Date('2026-10-14T17:00:00Z').getTime()

describe('healthDotStatus: Health tab dot rendering', () => {
  it('shows green dot when overall is green and not stale', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 5, copy: { ageS: 300 } }, NOW)
    expect(result.dot).toBe('green')
    expect(result.note).toBe('Overall: healthy')
  })

  it('shows yellow dot when overall is yellow', () => {
    const result = healthDotStatus({ overall: 'yellow', checksCount: 5, copy: {} }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toBe('Overall: degraded')
  })

  it('shows red dot when overall is red', () => {
    const result = healthDotStatus({ overall: 'red', checksCount: 5, copy: {} }, NOW)
    expect(result.dot).toBe('red')
    expect(result.note).toBe('Overall: critical')
  })

  it('shows amber dot with frozen-sweep note when stale', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 5, copy: { stale: true, ageS: 1200 } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toMatch(/frozen sweep · 20 min ago/)
  })

  it('shows amber dot with future-dated note when in future', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 5, copy: { future: true, ageS: 0 } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toMatch(/future-dated/)
  })

  it('shows grey dot for unrecognized overall severity', () => {
    const result = healthDotStatus({ overall: 'purple', checksCount: 5, copy: {} }, NOW)
    expect(result.dot).toBe('grey')
    expect(result.note).toBe('Overall: unrecognized')
  })

  it('handles stale yellow/red snapshots (amber with reason)', () => {
    const result = healthDotStatus({ overall: 'yellow', checksCount: 5, copy: { stale: true, ageS: 2400 } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toMatch(/frozen sweep · 40 min ago/)
  })

  it('renders without copy when it is missing', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 5 }, NOW)
    expect(result.dot).toBe('green')
    expect(result.note).toBe('Overall: healthy')
  })

  // Defect fixes: stale/future without ageS, empty snapshots, fallback never green
  it('handles stale snapshot with null ageS (renders "age unknown")', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 5, copy: { stale: true, ageS: null } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toMatch(/frozen sweep · age unknown/)
  })

  it('handles future-dated snapshot with null ageS (renders "age unknown")', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 5, copy: { future: true, ageS: null } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toMatch(/future-dated · age unknown/)
  })

  it('shows yellow/unknown when checksCount is 0 (empty snapshot, never green)', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 0, copy: { ageS: 300 } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toBe('Overall: unknown')
  })

  it('shows yellow/unknown when checksCount is null (missing check count, never green)', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: null, copy: { ageS: 300 } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.note).toBe('Overall: unknown')
  })

  it('fallback never returns green (unrecognized overall returns grey, not green)', () => {
    const result = healthDotStatus({ overall: 'unknown-severity', checksCount: 5, copy: {} }, NOW)
    expect(result.dot).toBe('grey')
    expect(result.dot).not.toBe('green')
  })

  it('stale+null-ageS never returns green even with green overall', () => {
    const result = healthDotStatus({ overall: 'green', checksCount: 5, copy: { stale: true, ageS: null } }, NOW)
    expect(result.dot).toBe('yellow')
    expect(result.dot).not.toBe('green')
  })
})
