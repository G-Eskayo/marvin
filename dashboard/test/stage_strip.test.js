import { describe, it, expect } from 'vitest'
import { deriveStageStrip } from '../src/lib/stage_strip.js'

describe('deriveStageStrip', () => {
  it('returns stages in canonical order regardless of event order', () => {
    const events = [
      { stage: 'merging', status: 'passed', timestamp: '2026-10-15T12:00:00Z' },
      { stage: 'claimed', status: 'started', timestamp: '2026-10-15T10:00:00Z' },
      { stage: 'gate', status: 'passed', timestamp: '2026-10-15T11:30:00Z' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip.map((s) => s.stage)).toEqual(['claimed', 'gate', 'merging'])
  })

  it('uses the latest event per stage when multiple exist', () => {
    const events = [
      { stage: 'gate', status: 'started', timestamp: '2026-10-15T11:00:00Z', detail: 'first' },
      { stage: 'gate', status: 'passed', timestamp: '2026-10-15T11:30:00Z', detail: 'second' },
      { stage: 'gate', status: 'passed', timestamp: '2026-10-15T11:15:00Z', detail: 'third' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip).toHaveLength(1)
    expect(strip[0].detail).toBe('second')
  })

  it('extracts remediation lines and stores them separately', () => {
    const events = [
      { stage: 'merging', status: 'failed', timestamp: '2026-10-15T12:00:00Z', detail: 'NOT_MERGEABLE: conflicts\n\nRemediation: Resolve the conflicts on GitHub' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].remediation).toBe('Resolve the conflicts on GitHub')
    expect(strip[0].detail).toBe('NOT_MERGEABLE: conflicts')
  })

  it('keeps detail as-is when no remediation line is present', () => {
    const events = [
      { stage: 'executing', status: 'failed', timestamp: '2026-10-15T12:00:00Z', detail: 'Test suite failed' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].remediation).toBe(null)
    expect(strip[0].detail).toBe('Test suite failed')
  })

  it('detects needs-rebase from REBASE_CONFLICT prefix on gate: failed', () => {
    const events = [
      { stage: 'gate', status: 'failed', timestamp: '2026-10-15T11:30:00Z', detail: 'REBASE_CONFLICT: Rebase onto main failed' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].needsRebase).toBe(true)
  })

  it('does not detect needs-rebase for other gate failures', () => {
    const events = [
      { stage: 'gate', status: 'failed', timestamp: '2026-10-15T11:30:00Z', detail: 'GATE_TESTS_FAILED: test suite' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].needsRebase).toBe(false)
  })

  it('includes running status when isLiveNow is true', () => {
    const events = [
      { stage: 'executing', status: 'started', timestamp: '2026-10-15T12:00:00Z' }
    ]
    const strip = deriveStageStrip(events, { isLiveNow: true, now: () => new Date('2026-10-15T12:05:00Z') })
    expect(strip[0].liveStatus).toBe('running')
  })

  it('includes stalled status when isLiveNow is true and age exceeds stall threshold', () => {
    const events = [
      { stage: 'executing', status: 'started', timestamp: '2026-10-15T10:00:00Z' }
    ]
    const strip = deriveStageStrip(events, { isLiveNow: true, now: () => new Date('2026-10-15T12:00:00Z') })
    expect(strip[0].liveStatus).toBe('stalled')
  })

  it('does not set liveStatus when isLiveNow is false', () => {
    const events = [
      { stage: 'executing', status: 'started', timestamp: '2026-10-15T12:00:00Z' }
    ]
    const strip = deriveStageStrip(events, { isLiveNow: false, now: () => new Date('2026-10-15T12:05:00Z') })
    expect(strip[0].liveStatus).toBe(null)
  })

  it('includes when and money fields in each stage', () => {
    const events = [
      { stage: 'claimed', status: 'started', timestamp: '2026-10-15T10:00:00Z', cost_usd: 0.02 }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].when).toMatch(/Oct/)
    expect(strip[0].money).toBe('$0.02')
  })

  it('formats money correctly for zero cost', () => {
    const events = [
      { stage: 'claimed', status: 'started', timestamp: '2026-10-15T10:00:00Z', cost_usd: 0 }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].money).toBe('$0.00')
  })

  it('formats money correctly for small amounts with 4 decimal places', () => {
    const events = [
      { stage: 'claimed', status: 'started', timestamp: '2026-10-15T10:00:00Z', cost_usd: 0.001 }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].money).toBe('$0.0010')
  })

  it('handles empty events array', () => {
    const strip = deriveStageStrip([])
    expect(strip).toEqual([])
  })

  it('returns empty array when no events are in terminal order', () => {
    const events = [
      { stage: 'unknown-stage', status: 'passed', timestamp: '2026-10-15T12:00:00Z' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip).toEqual([])
  })

  it('skips events with unknown stages', () => {
    const events = [
      { stage: 'claimed', status: 'started', timestamp: '2026-10-15T10:00:00Z' },
      { stage: 'unknown-stage', status: 'passed', timestamp: '2026-10-15T11:00:00Z' },
      { stage: 'merging', status: 'passed', timestamp: '2026-10-15T12:00:00Z' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip.map((s) => s.stage)).toEqual(['claimed', 'merging'])
  })

  it('only detects needsRebase on gate stage', () => {
    const events = [
      { stage: 'executing', status: 'failed', timestamp: '2026-10-15T12:00:00Z', detail: 'REBASE_CONFLICT: Rebase onto main failed' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].needsRebase).toBe(false)
  })

  it('applies liveStatus only to the most-recent-timestamped stage when isLiveNow is true', () => {
    const events = [
      { stage: 'claimed', status: 'started', timestamp: '2026-10-15T10:00:00Z' },
      { stage: 'gate', status: 'started', timestamp: '2026-10-15T11:30:00Z' },
      { stage: 'merging', status: 'started', timestamp: '2026-10-15T11:15:00Z' }
    ]
    const strip = deriveStageStrip(events, { isLiveNow: true, now: () => new Date('2026-10-15T12:00:00Z') })
    expect(strip.find((s) => s.stage === 'claimed').liveStatus).toBe(null)
    expect(strip.find((s) => s.stage === 'gate').liveStatus).toBe('running')
    expect(strip.find((s) => s.stage === 'merging').liveStatus).toBe(null)
  })

  it('does not apply liveStatus to non-started stages even if most recent', () => {
    const events = [
      { stage: 'gate', status: 'passed', timestamp: '2026-10-15T11:30:00Z' }
    ]
    const strip = deriveStageStrip(events, { isLiveNow: true, now: () => new Date('2026-10-15T12:00:00Z') })
    expect(strip[0].liveStatus).toBe(null)
  })

  it('keeps everything after Remediation: marker, not just one line', () => {
    const events = [
      { stage: 'merging', status: 'failed', timestamp: '2026-10-15T12:00:00Z',
        detail: 'NOT_MERGEABLE: conflicts\n\nRemediation: Step 1: Resolve conflicts\nStep 2: Push changes\nStep 3: Approve again' }
    ]
    const strip = deriveStageStrip(events)
    expect(strip[0].remediation).toBe('Step 1: Resolve conflicts\nStep 2: Push changes\nStep 3: Approve again')
    expect(strip[0].detail).toBe('NOT_MERGEABLE: conflicts')
  })

  it('detects running status only when stage is started', () => {
    const events = [
      { stage: 'gate', status: 'passed', timestamp: '2026-10-15T11:30:00Z' }
    ]
    const strip = deriveStageStrip(events, { isLiveNow: true, now: () => new Date('2026-10-15T12:00:00Z') })
    expect(strip[0].liveStatus).toBe(null)
  })

  it('marks most recent stage as stalled when age exceeds threshold', () => {
    const events = [
      { stage: 'gate', status: 'started', timestamp: '2026-10-15T10:00:00Z' }
    ]
    const strip = deriveStageStrip(events, { isLiveNow: true, now: () => new Date('2026-10-15T12:05:00Z') })
    expect(strip[0].liveStatus).toBe('stalled')
  })
})
