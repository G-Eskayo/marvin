import { describe, it, expect, beforeEach } from 'vitest'
import { deriveSegments } from '../src/lib/stage_strip.js'

describe('deriveSegments', () => {
  const now = new Date('2026-10-09T12:00:00Z').getTime()
  const oneHourAgo = now - 60 * 60 * 1000
  const twoMinAgo = now - 2 * 60 * 1000
  const eighteenMinAgo = now - 18 * 60 * 1000
  const fortyFiveMinAgo = now - 45 * 60 * 1000

  it('all-passed ticket renders every segment passed, no current', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      executing: { stage: 'executing', status: 'passed', timestamp: new Date(oneHourAgo - 20 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      verifying: { stage: 'verifying', status: 'passed', timestamp: new Date(oneHourAgo - 10 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      done: { stage: 'done', status: 'passed', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1', cost_usd: 0.05 },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).toHaveLength(5)
    expect(segments.map(s => s.status)).toEqual(['passed', 'passed', 'passed', 'passed', 'passed'])
    expect(segments.map(s => s.key)).toEqual(['claimed', 'planning', 'executing', 'verifying', 'done'])
  })

  it('failed at gate shows segment failed with message and remediation', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      executing: { stage: 'executing', status: 'passed', timestamp: new Date(oneHourAgo - 20 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      verifying: { stage: 'verifying', status: 'passed', timestamp: new Date(oneHourAgo - 10 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      gate: { stage: 'gate', status: 'failed', detail: 'GATE_TESTS_FAILED: some tests failed', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).toHaveLength(5)
    const gateSeg = segments.find(s => s.key === 'gate')
    expect(gateSeg.status).toBe('failed')
    expect(gateSeg.message).toContain('some tests failed')
    expect(gateSeg.remediation).toBeTruthy()
  })

  it('refused at order shows relabeled segment with message, no fabricated remediation', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      merging: { stage: 'merging', status: 'failed', detail: 'refused OUT_OF_ORDER: Merge #208 first', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).toHaveLength(3)
    const mergeSeg = segments.find(s => s.key === 'merging')
    expect(mergeSeg.status).toBe('failed')
    expect(mergeSeg.message).toContain('Merge #208 first')
    // OUT_OF_ORDER should have no remediation
    expect(mergeSeg.remediation).toBeFalsy()
  })

  it('running: latest started, isLiveNow true, recent → started (animated)', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      executing: { stage: 'executing', status: 'started', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: true, now })
    const executing = segments.find(s => s.key === 'executing')
    expect(executing.status).toBe('started')
  })

  it('#161 regression: latest started, isLiveNow false → stalled', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      executing: { stage: 'executing', status: 'started', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const executing = segments.find(s => s.key === 'executing')
    expect(executing.status).toBe('stalled')
  })

  it('live but silent: isLiveNow true, last event 45 min old → stalled', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      executing: { stage: 'executing', status: 'started', timestamp: new Date(fortyFiveMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: true, stallMinutes: 30, now })
    const executing = segments.find(s => s.key === 'executing')
    expect(executing.status).toBe('stalled')
  })

  it('two-phase lifecycle: done/passed then later gate→merging→done', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      executing: { stage: 'executing', status: 'passed', timestamp: new Date(oneHourAgo - 20 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      verifying: { stage: 'verifying', status: 'passed', timestamp: new Date(oneHourAgo - 10 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      done_1: { stage: 'done', status: 'passed', timestamp: new Date(oneHourAgo - 5 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      gate: { stage: 'gate', status: 'passed', timestamp: new Date(eighteenMinAgo).toISOString(), machine: 'mac-mini-1' },
      merging: { stage: 'merging', status: 'passed', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).toHaveLength(6)
    const gateIdx = segments.findIndex(s => s.key === 'gate')
    expect(gateIdx).toBeGreaterThan(-1)
    expect(segments[gateIdx].status).toBe('passed')
  })

  it('rebase prop conflict → extra failed segment', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(oneHourAgo - 30 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, rebase: { status: 'conflict', files: ['foo.js'] }, now })
    const rebaseSeg = segments.find(s => s.key === 'rebase')
    expect(rebaseSeg).toBeTruthy()
    expect(rebaseSeg.status).toBe('failed')
  })

  it('rebase prop clean → no phantom segment', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, rebase: { status: 'clean' }, now })
    expect(segments.find(s => s.key === 'rebase')).toBeFalsy()
  })

  it('empty events → all pending, no crash', () => {
    const stages = {}
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).toHaveLength(0)
  })

  it('unknown stage key → ignored, not thrown', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      unknown: { stage: 'unknown_stage', status: 'passed', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    expect(() => deriveSegments(stages, { isLiveNow: false, now })).not.toThrow()
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments.find(s => s.key === 'unknown_stage')).toBeFalsy()
  })

  it('unknown refusal code → message only, no crash', () => {
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(oneHourAgo).toISOString(), machine: 'mac-mini-1' },
      merging: { stage: 'merging', status: 'failed', detail: 'refused FUTURE_CODE: some new reason', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const mergeSeg = segments.find(s => s.key === 'merging')
    expect(mergeSeg.message).toContain('some new reason')
    expect(mergeSeg.remediation).toBeFalsy()
  })

  it('isLiveNow lookup throws → defaults to not live', () => {
    const stages = {
      executing: { stage: 'executing', status: 'started', timestamp: new Date(twoMinAgo).toISOString(), machine: 'mac-mini-1' },
    }
    const segments = deriveSegments(stages, { isLiveNow: () => { throw new Error('file missing') }, now })
    const executing = segments.find(s => s.key === 'executing')
    expect(executing.status).toBe('stalled')
  })
})
