import { describe, it, expect } from 'vitest'
import { deriveStageStrip } from '../src/lib/stage_strip.js'

const event = (stage, status = 'passed', over = {}) => ({
  stage,
  status,
  timestamp: '2026-10-01T12:00:00Z',
  machine: 'mac-mini',
  cost_usd: 0.05,
  ...over
})

const refusal = (prUrl, code, over = {}) => ({
  pr_url: prUrl,
  code,
  t: '2026-10-01T13:00:00Z',
  message: 'test refusal',
  ...over
})

const now = () => new Date('2026-10-01T14:00:00Z').getTime()

describe('deriveStageStrip', () => {
  it('returns empty segments for no events or refusals', () => {
    const result = deriveStageStrip({ events: [], refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments).toEqual([])
    expect(result.totalCostUsd).toBe(0)
  })

  it('creates one segment per stage event', () => {
    const events = [event('claimed'), event('planning'), event('executing')]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments.length).toBe(3)
    expect(result.segments.map((s) => s.stage)).toEqual(['claimed', 'planning', 'executing'])
  })

  it('marks passed stages with a checkmark', () => {
    const events = [event('claimed', 'passed')]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments[0]).toMatchObject({
      stage: 'claimed',
      status: 'passed',
      icon: '✓',
      color: 'emerald'
    })
  })

  it('marks failed stages with an X', () => {
    const events = [event('executing', 'failed', { detail: 'tests failed' })]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments[0]).toMatchObject({
      stage: 'executing',
      status: 'failed',
      icon: '✕',
      color: 'red'
    })
  })

  it('marks started/incomplete stages with a dot', () => {
    const events = [event('verifying', 'started', { timestamp: '2026-10-01T13:50:00Z' })]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments[0]).toMatchObject({
      status: 'started',
      icon: '●',
      color: 'blue'
    })
  })

  it('marks stalled stages (no activity for stallMinutes) in amber', () => {
    const events = [event('verifying', 'started', { timestamp: '2026-10-01T13:00:00Z' })]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments[0]).toMatchObject({
      stalled: true,
      color: 'amber'
    })
  })

  it('links refusals to their preceding stage by PR URL', () => {
    const prUrl = 'https://github.com/G-Eskayo/marvin/pull/42'
    const events = [event('gate', 'started')]
    const refusals = [refusal(prUrl, 'GATE_TESTS_FAILED')]
    const result = deriveStageStrip({ events, refusals, labels: [], now, stallMinutes: 30 })
    expect(result.segments[0]).toMatchObject({
      stage: 'gate',
      refusal: { code: 'GATE_TESTS_FAILED', reason: 'tests failed' },
      color: 'red'
    })
  })

  it('handles multiple refusals on the same ticket (e.g. denied twice)', () => {
    const prUrl = 'https://github.com/G-Eskayo/marvin/pull/42'
    const events = [
      event('gate', 'failed', { timestamp: '2026-10-01T12:00:00Z' }),
      event('gate', 'failed', { timestamp: '2026-10-01T13:00:00Z' })
    ]
    const refusals = [
      refusal(prUrl, 'GATE_TESTS_FAILED', { t: '2026-10-01T12:30:00Z' }),
      refusal(prUrl, 'CI_FAILED', { t: '2026-10-01T13:30:00Z' })
    ]
    const result = deriveStageStrip({ events, refusals, labels: [], now, stallMinutes: 30 })
    expect(result.segments.length).toBe(2)
    expect(result.segments[0].refusal.code).toBe('GATE_TESTS_FAILED')
    expect(result.segments[1].refusal.code).toBe('CI_FAILED')
  })

  it('marks a stage waiting-on-human (needs-reengagement label) with a person icon', () => {
    const events = [event('gate', 'failed')]
    const result = deriveStageStrip({ events, refusals: [], labels: ['needs-reengagement'], now, stallMinutes: 30 })
    expect(result.segments[0]).toMatchObject({
      stage: 'gate',
      color: 'gray',
      icon: '👤'
    })
  })

  it('accumulates total cost from all stages', () => {
    const events = [event('claimed', 'passed', { cost_usd: 0.05 }), event('executing', 'passed', { cost_usd: 0.10 })]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.totalCostUsd).toBe(0.15)
  })

  it('preserves stage order even when refusals arrive out of order', () => {
    const prUrl = 'https://github.com/G-Eskayo/marvin/pull/42'
    const events = [event('gate', 'failed'), event('merging', 'failed')]
    const refusals = [
      refusal(prUrl, 'CI_FAILED', { t: '2026-10-01T13:30:00Z' }),
      refusal(prUrl, 'MERGE_REFUSED', { t: '2026-10-01T13:00:00Z' })
    ]
    const result = deriveStageStrip({ events, refusals, labels: [], now, stallMinutes: 30 })
    expect(result.segments.map((s) => s.stage)).toEqual(['gate', 'merging'])
  })

  it('includes machine, cost and timestamp for hover tooltip', () => {
    const events = [event('executing', 'passed', { machine: 'mac-laptop', cost_usd: 0.07, timestamp: '2026-10-01T12:30:00Z' })]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments[0]).toMatchObject({
      machine: 'mac-laptop',
      costUsd: 0.07,
      timestamp: '2026-10-01T12:30:00Z'
    })
  })

  it('computes elapsed time for running stages', () => {
    const events = [event('executing', 'started', { timestamp: '2026-10-01T13:00:00Z' })]
    const result = deriveStageStrip({ events, refusals: [], labels: [], now, stallMinutes: 30 })
    expect(result.segments[0].elapsedMinutes).toBe(60)
  })
})
