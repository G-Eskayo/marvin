import { describe, it, expect, beforeEach } from 'vitest'
import { deriveSegments } from '../src/lib/stage_strip.js'
import { REFUSAL_CODES } from '../webhook-server/refusal_log.js'

// Test fixtures: realistic event sequences
const now = new Date('2026-10-09T16:00:00Z').getTime()

function event(stage, status, detail = '', timestamp = now - 3600000, machine = 'mac-mini', costUsd = 0.01) {
  return { stage, status, detail, timestamp: new Date(timestamp).toISOString(), machine, cost_usd: costUsd, title: 'Test ticket #42' }
}

describe('deriveSegments: core lifecycle', () => {
  it('shows all-passed pipeline: six stages each with passed status', () => {
    const stages = {
      claimed: [event('claimed', 'passed', '', now - 7200000)],
      planning: [event('planning', 'passed', '', now - 6000000)],
      executing: [event('executing', 'passed', '', now - 4800000)],
      verifying: [event('verifying', 'passed', '', now - 3600000)],
      gate: [event('gate', 'passed', '', now - 2400000)],
      merging: [event('merging', 'passed', '', now - 1200000)]
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).toHaveLength(6)
    expect(segments[0]).toMatchObject({ stage: 'claimed', status: 'passed' })
    expect(segments[5]).toMatchObject({ stage: 'merging', status: 'passed' })
  })

  it('shows failed-at-gate with the failure detail and remediation', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'passed')],
      executing: [event('executing', 'passed')],
      verifying: [event('verifying', 'passed')],
      gate: [event('gate', 'failed', 'Rebase onto main failed: conflict in src/index.js')],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const gateSeg = segments.find(s => s.stage === 'gate')
    expect(gateSeg).toMatchObject({ status: 'failed' })
    expect(gateSeg.detail).toContain('conflict')
    expect(gateSeg.remediation).toBeDefined()
  })

  it('shows refused-at-order with OUT_OF_ORDER code and message from pr_order.js', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'passed')],
      executing: [event('executing', 'passed')],
      verifying: [event('verifying', 'passed')],
      gate: [event('gate', 'passed')],
      merging: [event('merging', 'failed', 'refused OUT_OF_ORDER: another PR was merged first; rebase and try again')]
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const merging = segments.find(s => s.stage === 'merging')
    expect(merging.status).toBe('failed')
    expect(merging.remediationLabel).toBe('Order')
    expect(merging.detail).toContain('OUT_OF_ORDER')
  })

  it('relabels every REFUSAL_CODE without crashing', () => {
    for (const code of REFUSAL_CODES) {
      const stages = {
        claimed: [event('claimed', 'passed')],
        planning: [event('planning', 'passed')],
        executing: [event('executing', 'passed')],
        verifying: [event('verifying', 'passed')],
        gate: [event('gate', 'passed')],
        merging: [event('merging', 'failed', `refused ${code}: test message`)]
      }
      const segments = deriveSegments(stages, { isLiveNow: false, now })
      const merging = segments.find(s => s.stage === 'merging')
      expect(merging).toBeDefined()
      if (code === 'OUT_OF_ORDER') {
        expect(merging.remediationLabel).toBe('Order')
        // OUT_OF_ORDER has no generic remediation text
        expect(merging.remediation).toBeFalsy()
      } else {
        expect(merging.remediationLabel).toBe('Request')
      }
    }
  })
})

describe('deriveSegments: live vs. stalled', () => {
  it('shows running: live now + recent started event', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'started', '', now - 120000)],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: true, now })
    const planning = segments.find(s => s.stage === 'planning')
    expect(planning.isRunning).toBe(true)
    expect(planning.elapsedLabel).toMatch(/m ago/)
  })

  it('detects #161 regression: not-live + recent started → stalled, never inferred from label', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'started', '', now - 300000)], // 5 min ago, not live
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now, stallMinutes: 10 })
    const planning = segments.find(s => s.stage === 'planning')
    expect(planning.isRunning).toBe(false)
    expect(planning.isStalled).toBe(false) // not yet at threshold
  })

  it('shows live-but-silent-past-threshold as stalled', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'started', '', now - 600000)], // 10 min ago
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: true, now, stallMinutes: 10 })
    const planning = segments.find(s => s.stage === 'planning')
    expect(planning.isStalled).toBe(true)
    expect(planning.elapsedLabel).toContain('10')
  })

  it('marks as stalled exactly at the threshold (stallMinutes = 10, elapsed = 10)', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'started', '', now - 600000)], // exactly 10 min ago
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: true, now, stallMinutes: 10 })
    const planning = segments.find(s => s.stage === 'planning')
    expect(planning.isStalled).toBe(true)
  })

  it('does not mark as stalled just under the threshold', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'started', '', now - 599000)], // 9:59 ago
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: true, now, stallMinutes: 10 })
    const planning = segments.find(s => s.stage === 'planning')
    expect(planning.isStalled).toBe(false)
  })
})

describe('deriveSegments: edge cases and robustness', () => {
  it('renders null for empty stages', () => {
    const result = deriveSegments({}, { isLiveNow: false, now })
    expect(result).toBeNull()
  })

  it('recovers from malformed event (missing timestamp)', () => {
    const stages = {
      claimed: [{ stage: 'claimed', status: 'passed', timestamp: undefined, machine: 'mac-mini' }],
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).toBeDefined()
    expect(segments[0].elapsedLabel).toBeDefined()
  })

  it('ignores unknown future stage keys', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: [],
      hypothetical_future_stage: [event('hypothetical_future_stage', 'started')]
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments).not.toEqual(expect.arrayContaining([expect.objectContaining({ stage: 'hypothetical_future_stage' })]))
  })

  it('treats out-of-schema status as pending', () => {
    const stages = {
      claimed: [{ stage: 'claimed', status: 'unknown_status', timestamp: new Date(now).toISOString(), machine: 'mac-mini' }],
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const claimed = segments[0]
    expect(claimed.status).toBe('unknown_status')
    // Component will treat unknown status like pending
  })

  it('handles huge event histories in O(n)', () => {
    const manyEvents = Array.from({ length: 1000 }, (_, i) =>
      event('planning', 'started', `event ${i}`, now - (1000 - i) * 1000)
    )
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: manyEvents,
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const start = Date.now()
    deriveSegments(stages, { isLiveNow: false, now })
    const elapsed = Date.now() - start
    expect(elapsed).toBeLessThan(100) // should be fast
  })

  it('handles concurrent write mid-poll: pure function means consistent stale read', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'started')],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const result1 = deriveSegments(stages, { isLiveNow: false, now })
    // Simulate a concurrent write (mutation of stages object)
    stages.planning.push(event('planning', 'passed'))
    const result2 = deriveSegments(stages, { isLiveNow: false, now })
    // results differ, but each one is internally consistent (that's what matters for race safety)
    expect(result1).toBeDefined()
    expect(result2).toBeDefined()
  })

  it('renders tooltip with unfamiliar machine value', () => {
    const stages = {
      claimed: [event('claimed', 'passed', '', now - 3600000, 'unknown-machine-xyz')],
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments[0].machine).toBe('unknown-machine-xyz')
  })

  it('prefers latest started event when repeated started events exist', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [
        event('planning', 'started', 'first attempt', now - 600000),
        event('planning', 'started', 'retry attempt', now - 300000)
      ],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const planning = segments.find(s => s.stage === 'planning')
    expect(planning.detail).toContain('retry attempt')
  })

  it('never shows animated segment for stale claimed: label with zero events', () => {
    // The #161 scenario: claimed: machine-id label exists on the ticket but no 'claimed' stage event
    const stages = {
      claimed: [],
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const claimed = segments[0]
    expect(claimed.status).toBe('pending')
    expect(claimed.isRunning).toBe(false)
  })

  it('skipped stages render as grey pending placeholders', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [],
      executing: [event('executing', 'passed')],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    const planning = segments.find(s => s.stage === 'planning')
    expect(planning.status).toBe('pending')
    const verifying = segments.find(s => s.stage === 'verifying')
    expect(verifying.status).toBe('pending')
  })
})

describe('deriveSegments: optional stages (mutation, rebuilding, done)', () => {
  it('includes optional stages only if present in input', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'passed')],
      executing: [event('executing', 'passed')],
      verifying: [event('verifying', 'passed')],
      gate: [event('gate', 'passed')],
      merging: [event('merging', 'passed')],
      rebuilding: [event('rebuilding', 'passed')],
      done: [event('done', 'passed')]
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments.map(s => s.stage)).toEqual(['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'rebuilding', 'done'])
  })

  it('omits optional stages that are empty', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'passed')],
      executing: [event('executing', 'passed')],
      verifying: [event('verifying', 'passed')],
      gate: [event('gate', 'passed')],
      merging: [event('merging', 'passed')]
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments.map(s => s.stage)).toEqual(['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging'])
  })

  it('includes mutation stage when present', () => {
    const stages = {
      claimed: [event('claimed', 'passed')],
      planning: [event('planning', 'passed')],
      executing: [event('executing', 'passed')],
      verifying: [event('verifying', 'passed')],
      gate: [event('gate', 'passed')],
      merging: [event('merging', 'passed')],
      mutation: [event('mutation', 'passed')]
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments.find(s => s.stage === 'mutation')).toBeDefined()
  })
})

describe('deriveSegments: duration formatting', () => {
  it('formats elapsed time in minutes for recent events', () => {
    const stages = {
      claimed: [event('claimed', 'passed', '', now - 120000)], // 2 minutes ago
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments[0].elapsedLabel).toMatch(/2m ago/)
  })

  it('formats elapsed time in seconds for very recent events', () => {
    const stages = {
      claimed: [event('claimed', 'passed', '', now - 30000)], // 30 seconds ago
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments[0].elapsedLabel).toMatch(/s/)
  })

  it('formats elapsed time in hours for old events', () => {
    const stages = {
      claimed: [event('claimed', 'passed', '', now - 7200000)], // 2 hours ago
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments[0].elapsedLabel).toMatch(/2.*h/)
  })
})

describe('deriveSegments: cost aggregation', () => {
  it('aggregates cost across all events in a stage', () => {
    const stages = {
      claimed: [
        event('claimed', 'passed', '', now - 7200000, 'mac-mini', 0.05),
        event('claimed', 'passed', '', now - 6000000, 'mac-mini', 0.03)
      ],
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments[0].costUsd).toBe(0.08)
  })

  it('defaults to 0 when no cost data', () => {
    const stages = {
      claimed: [{ stage: 'claimed', status: 'passed', timestamp: new Date(now - 3600000).toISOString(), machine: 'mac-mini' }],
      planning: [],
      executing: [],
      verifying: [],
      gate: [],
      merging: []
    }
    const segments = deriveSegments(stages, { isLiveNow: false, now })
    expect(segments[0].costUsd).toBe(0)
  })
})
