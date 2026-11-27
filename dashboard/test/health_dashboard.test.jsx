import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { OverallBadge } from '../src/components/HealthDashboard.jsx'

describe('OverallBadge: Health tab verdict rendering', () => {
  it('shows stale state when copy.stale is true', () => {
    const staleStatus = {
      overall: 'green',
      generatedAt: new Date('2026-10-14T16:00:00Z'),
      checksCount: 1,
      copy: { ageS: 3600, stale: true, future: false, host: null }
    }
    const html = renderToStaticMarkup(
      <OverallBadge {...staleStatus} refreshing={false} onRefresh={() => {}} />
    )
    expect(html).toContain('SWEEP FROZEN')
    expect(html).toContain('AGO')
    // Should have amber color (yellow bg)
    expect(html).toContain('bg-amber-950')
  })

  it('shows healthy state when overall is green and not stale', () => {
    const freshStatus = {
      overall: 'green',
      generatedAt: new Date('2026-10-14T16:55:00Z'),
      checksCount: 1,
      copy: { ageS: 300, stale: false, future: false, host: null }
    }
    const html = renderToStaticMarkup(
      <OverallBadge {...freshStatus} refreshing={false} onRefresh={() => {}} />
    )
    expect(html).toContain('HEALTHY')
    expect(html).toContain('AGO')
    // Should have green color
    expect(html).toContain('bg-emerald-950')
  })

  it('shows unknown when overall is an unrecognized value', () => {
    const badStatus = {
      overall: 'purple',
      generatedAt: new Date('2026-10-14T16:55:00Z'),
      checksCount: 5,
      copy: { ageS: 300, stale: false, future: false }
    }
    const html = renderToStaticMarkup(
      <OverallBadge {...badStatus} refreshing={false} onRefresh={() => {}} />
    )
    expect(html).toContain('HEALTH UNCONFIRMED')
    // Should have warning color (yellow)
    expect(html).toContain('bg-amber-950')
  })

  it('shows unknown when checksCount is 0', () => {
    const emptyStatus = {
      overall: 'green',
      generatedAt: new Date('2026-10-14T16:55:00Z'),
      checksCount: 0,
      copy: { ageS: 300, stale: false, future: false }
    }
    const html = renderToStaticMarkup(
      <OverallBadge {...emptyStatus} refreshing={false} onRefresh={() => {}} />
    )
    expect(html).toContain('HEALTH UNKNOWN')
  })

  it('shows future-dated state when copy.future is true', () => {
    const futureStatus = {
      overall: 'green',
      generatedAt: new Date('2026-10-14T17:05:00Z'),
      checksCount: 1,
      copy: { ageS: 0, future: true, stale: false }
    }
    const html = renderToStaticMarkup(
      <OverallBadge {...futureStatus} refreshing={false} onRefresh={() => {}} />
    )
    expect(html).toContain('FUTURE-DATED SNAPSHOT')
    // Should have amber color
    expect(html).toContain('bg-amber-950')
  })

  it('shows critical when overall is red', () => {
    const criticalStatus = {
      overall: 'red',
      generatedAt: new Date('2026-10-14T16:55:00Z'),
      checksCount: 5,
      copy: { ageS: 300, stale: false, future: false }
    }
    const html = renderToStaticMarkup(
      <OverallBadge {...criticalStatus} refreshing={false} onRefresh={() => {}} />
    )
    expect(html).toContain('CRITICAL')
    // Should have red color
    expect(html).toContain('bg-red-950')
  })

  it('shows degraded when overall is yellow', () => {
    const degradedStatus = {
      overall: 'yellow',
      generatedAt: new Date('2026-10-14T16:55:00Z'),
      checksCount: 5,
      copy: { ageS: 300, stale: false, future: false }
    }
    const html = renderToStaticMarkup(
      <OverallBadge {...degradedStatus} refreshing={false} onRefresh={() => {}} />
    )
    expect(html).toContain('DEGRADED')
    // Should have amber color
    expect(html).toContain('bg-amber-950')
  })
})
