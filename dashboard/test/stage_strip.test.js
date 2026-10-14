import { describe, it, expect } from 'vitest'
import { deriveSegments, VALID_STAGES, STAGE_LABEL } from '../src/lib/stage_strip'

describe('deriveSegments', () => {
  // Test 1: null/undefined/empty array should return []
  it('returns empty array for null events', () => {
    expect(deriveSegments(null)).toEqual([])
  })

  it('returns empty array for undefined events', () => {
    expect(deriveSegments(undefined)).toEqual([])
  })

  it('returns empty array for empty array', () => {
    expect(deriveSegments([])).toEqual([])
  })

  it('returns empty array for non-array input', () => {
    expect(deriveSegments('not an array')).toEqual([])
    expect(deriveSegments(123)).toEqual([])
    expect(deriveSegments({})).toEqual([])
  })

  // Test 2: Large event count (retry storm shape)
  it('handles 5000 events with minimal processing time', () => {
    const events = []
    for (let i = 0; i < 5000; i++) {
      events.push({
        stage: 'gate',
        status: i % 2 === 0 ? 'failed' : 'started',
        detail: `Attempt ${i}`,
        timestamp: new Date().toISOString(),
        machine: 'test',
        cost_usd: 0.01
      })
    }
    const start = Date.now()
    const segments = deriveSegments(events)
    const elapsed = Date.now() - start

    expect(elapsed).toBeLessThan(1000)
    expect(segments.length).toBe(1)
    expect(segments[0].stage).toBe('gate')
    expect(segments[0].events.length).toBe(5000)
  })

  // Test 3: Unknown/garbage stage names
  it('ignores unknown stage names', () => {
    const events = [
      { stage: 'claimed', status: 'passed', timestamp: new Date().toISOString() },
      { stage: 'frobnicate', status: 'passed', timestamp: new Date().toISOString() },
      { stage: '', status: 'passed', timestamp: new Date().toISOString() },
      { stage: null, status: 'passed', timestamp: new Date().toISOString() },
      { stage: 'planning', status: 'passed', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    expect(segments.length).toBe(2)
    expect(segments[0].stage).toBe('claimed')
    expect(segments[1].stage).toBe('planning')
  })

  // Test 4: Unknown status doesn't crash
  it('handles unknown status values', () => {
    const events = [
      { stage: 'claimed', status: 'unknown-status', timestamp: new Date().toISOString(), detail: '' }
    ]
    const segments = deriveSegments(events)
    expect(segments.length).toBe(1)
    expect(segments[0].status).toBe('unknown-status')
  })

  // Test 5: Missing/invalid timestamp
  it('handles missing timestamp gracefully', () => {
    const events = [
      { stage: 'claimed', status: 'started', timestamp: '', machine: 'test', detail: '' },
      { stage: 'planning', status: 'started', timestamp: null, machine: 'test', detail: '' },
      { stage: 'executing', status: 'started', timestamp: 'not-a-date', machine: 'test', detail: '' }
    ]
    const segments = deriveSegments(events, { isLiveNow: true, stallMinutes: 30 })
    expect(segments[0].status).toBe('stalled')
    expect(segments[1].status).toBe('stalled')
    expect(segments[2].status).toBe('stalled')
  })

  // Test 6: Missing/invalid cost_usd
  it('handles missing or invalid cost_usd', () => {
    const events = [
      { stage: 'claimed', status: 'passed', detail: '', timestamp: new Date().toISOString(), cost_usd: null },
      { stage: 'planning', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'executing', status: 'passed', detail: '', timestamp: new Date().toISOString(), cost_usd: -5 },
      { stage: 'verifying', status: 'passed', detail: '', timestamp: new Date().toISOString(), cost_usd: 1e9 }
    ]
    const segments = deriveSegments(events)
    expect(segments[0].cost).toBe(0)
    expect(segments[1].cost).toBe(0)
    expect(segments[2].cost).toBe(-5)
    expect(segments[3].cost).toBe(1e9)
  })

  // Test 7: Missing/empty machine field
  it('handles missing or empty machine field', () => {
    const events = [
      { stage: 'claimed', status: 'passed', detail: '', timestamp: new Date().toISOString(), machine: '' },
      { stage: 'planning', status: 'passed', detail: '', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    expect(segments[0].events[0].machine).toBe('')
    expect(segments[1].events[0]).toBeDefined()
  })

  // Test 8: XSS/injection in detail field
  it('passes detail text through without escaping (component handles that)', () => {
    const events = [
      { stage: 'claimed', status: 'passed', detail: '<script>alert(1)</script>', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    expect(segments[0].message).toBe('<script>alert(1)</script>')
  })

  // Test 9: Refusal with empty code/message
  it('handles refusals with empty code or message', () => {
    const events = [
      { stage: 'merging', status: 'failed', detail: 'refused ', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    // Should result in the merging event unchanged since parsing fails
    expect(segments[0].stage).toBe('merging')
    expect(segments[0].status).toBe('failed')
  })

  // Test 10: Events not sorted by timestamp (clock skew)
  it('uses array order, not timestamp sort, for determining latest', () => {
    const now = new Date()
    const oldTime = new Date(now.getTime() - 10000).toISOString()
    const newTime = new Date(now.getTime() + 10000).toISOString()

    const events = [
      { stage: 'claimed', status: 'passed', detail: 'first', timestamp: newTime },
      { stage: 'claimed', status: 'failed', detail: 'second', timestamp: oldTime }
    ]
    const segments = deriveSegments(events)
    expect(segments[0].status).toBe('failed') // Last in array order
    expect(segments[0].message).toBe('second')
  })

  // Test 11: Ticket re-dispatched (claimed…done followed by new claimed)
  it('reflects new cycle after done when ticket is re-dispatched', () => {
    const events = [
      { stage: 'claimed', status: 'passed', detail: 'cycle 1', timestamp: new Date().toISOString() },
      { stage: 'planning', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'done', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'claimed', status: 'passed', detail: 'cycle 2', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    expect(segments.length).toBe(3) // One per unique stage (claimed, planning, done)
    const claimedSegment = segments.find(s => s.stage === 'claimed')
    expect(claimedSegment.message).toBe('cycle 2') // Latest claimed value
  })

  // Test 12: isLiveNow omitted defaults to safe stalled
  it('defaults to stalled when isLiveNow omitted', () => {
    const events = [
      { stage: 'claimed', status: 'started', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events) // isLiveNow defaults to false
    expect(segments[0].status).toBe('stalled')
  })

  // Test 13: conflicts && sentBack both true
  it('gives sentBack precedence over conflicts', () => {
    const segments = deriveSegments([], {
      conflicts: true,
      sentBack: true,
      isLiveNow: false
    })
    // sentBack is true, so no needs-rebase segment should be added
    const needsRebaseSegment = segments.find(s => s.stage === 'needs-rebase')
    expect(needsRebaseSegment).toBeUndefined()
  })

  // Test 14: Forward-compat unknown CODE
  it('falls back to generic request for unknown refusal code', () => {
    const events = [
      { stage: 'merging', status: 'failed', detail: 'refused BRAND_NEW_CODE: something new', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    const requestSegment = segments.find(s => s.stage === 'request')
    expect(requestSegment).toBeDefined()
    expect(requestSegment.status).toBe('failed')
  })

  // Test 15: Determinism
  it('returns deterministic output for identical input', () => {
    const events = [
      { stage: 'claimed', status: 'passed', detail: 'test', timestamp: new Date().toISOString(), machine: 'mac-mini', cost_usd: 0.5 },
      { stage: 'planning', status: 'passed', detail: '', timestamp: new Date().toISOString(), machine: 'mac-mini', cost_usd: 1.5 }
    ]
    const segments1 = deriveSegments(events, { stallMinutes: 30 })
    const segments2 = deriveSegments(events, { stallMinutes: 30 })
    expect(segments1).toEqual(segments2)
  })

  // Test 16: OUT_OF_ORDER refusal maps to 'order' segment
  it('maps OUT_OF_ORDER refusal to order segment', () => {
    const events = [
      { stage: 'merging', status: 'failed', detail: 'refused OUT_OF_ORDER: Merge #208 first', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    const orderSegment = segments.find(s => s.stage === 'order')
    expect(orderSegment).toBeDefined()
    expect(orderSegment.status).toBe('failed')
    expect(orderSegment.message).toContain('Merge #208')
  })

  // Test 16b: WRONG_BASE refusal maps to 'order' segment
  it('maps WRONG_BASE refusal to order segment', () => {
    const events = [
      { stage: 'merging', status: 'failed', detail: 'refused WRONG_BASE: Rebase first', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    const orderSegment = segments.find(s => s.stage === 'order')
    expect(orderSegment).toBeDefined()
    expect(orderSegment.status).toBe('failed')
  })

  // Test 17: SENT_BACK refusal maps to 'request' segment
  it('maps SENT_BACK refusal to request segment', () => {
    const events = [
      { stage: 'merging', status: 'failed', detail: 'refused SENT_BACK: Rework needed', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    const requestSegment = segments.find(s => s.stage === 'request')
    expect(requestSegment).toBeDefined()
    expect(requestSegment.status).toBe('failed')
  })

  // Test 17b: CI_PENDING refusal maps to 'request' segment
  it('maps CI_PENDING refusal to request segment', () => {
    const events = [
      { stage: 'merging', status: 'failed', detail: 'refused CI_PENDING: Wait for CI', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    const requestSegment = segments.find(s => s.stage === 'request')
    expect(requestSegment).toBeDefined()
  })

  // Test 18: Checks status passed
  it('derives passed status from checks.state passing', () => {
    const segments = deriveSegments([], { checks: { state: 'passing' } })
    const checksSegment = segments.find(s => s.stage === 'checks')
    expect(checksSegment.status).toBe('passed')
  })

  // Test 19: Checks status pending
  it('derives started status from checks.state pending', () => {
    const segments = deriveSegments([], { checks: { state: 'pending', pending: ['build', 'test'] } })
    const checksSegment = segments.find(s => s.stage === 'checks')
    expect(checksSegment.status).toBe('started')
    expect(checksSegment.message).toContain('build')
    expect(checksSegment.message).toContain('test')
  })

  // Test 20: Checks status failing
  it('derives failed status from checks.state failing', () => {
    const segments = deriveSegments([], { checks: { state: 'failing', failing: ['unit tests'] } })
    const checksSegment = segments.find(s => s.stage === 'checks')
    expect(checksSegment.status).toBe('failed')
    expect(checksSegment.message).toContain('unit tests')
  })

  // Test 21: needs-rebase segment (conflicts but not sentBack)
  it('adds needs-rebase segment when conflicts and not sentBack', () => {
    const segments = deriveSegments([], {
      conflicts: true,
      sentBack: false,
      isLiveNow: false
    })
    const rebaseSegment = segments.find(s => s.stage === 'needs-rebase')
    expect(rebaseSegment).toBeDefined()
    expect(rebaseSegment.status).toBe('blocked')
  })

  // Test 22: isLiveNow true keeps 'started' as started within stallMinutes
  it('keeps started status within stallMinutes when isLiveNow is true', () => {
    const recentTime = new Date(Date.now() - 1000).toISOString()
    const events = [
      { stage: 'claimed', status: 'started', timestamp: recentTime }
    ]
    const segments = deriveSegments(events, { isLiveNow: true, stallMinutes: 30 })
    expect(segments[0].status).toBe('started')
  })

  // Test 23: isLiveNow true makes started 'stalled' after stallMinutes
  it('marks started as stalled after stallMinutes when isLiveNow is true', () => {
    const oldTime = new Date(Date.now() - 35 * 60000).toISOString()
    const events = [
      { stage: 'claimed', status: 'started', timestamp: oldTime }
    ]
    const segments = deriveSegments(events, { isLiveNow: true, stallMinutes: 30 })
    expect(segments[0].status).toBe('stalled')
  })

  // Test 24: STAGE_LABEL export
  it('exports STAGE_LABEL with all valid stages', () => {
    for (const stage of VALID_STAGES) {
      expect(STAGE_LABEL[stage]).toBeDefined()
      expect(typeof STAGE_LABEL[stage]).toBe('string')
    }
  })

  // Test 16b: order/request with no gate yet
  it('inserts order/request at end when gate has not run yet', () => {
    const events = [
      { stage: 'claimed', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'merging', status: 'failed', detail: 'refused OUT_OF_ORDER: Merge #208 first', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    const orderIdx = segments.findIndex(s => s.stage === 'order')
    expect(orderIdx).toBeGreaterThanOrEqual(0)
    expect(segments[orderIdx].status).toBe('failed')
  })

  // Test 17: now parameter threaded through statusOfEvent
  it('uses injected now parameter for deterministic stall detection', () => {
    const fixedNow = new Date('2026-01-01T12:00:00Z').getTime()
    const oldTime = new Date('2026-01-01T11:00:00Z').toISOString()
    const events = [
      { stage: 'claimed', status: 'started', timestamp: oldTime }
    ]
    const segments = deriveSegments(events, { now: fixedNow, isLiveNow: true, stallMinutes: 30 })
    expect(segments[0].status).toBe('stalled') // exactly 60 mins ago, > 30 min threshold
  })

  // Test 18: order/request insertion before already-recorded gate
  it('inserts order segment before gate when gate already has events', () => {
    const events = [
      { stage: 'claimed', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'gate', status: 'passed', detail: 'passed', timestamp: new Date().toISOString() },
      { stage: 'merging', status: 'failed', detail: 'refused OUT_OF_ORDER: Merge #208 first', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    const orderIdx = segments.findIndex(s => s.stage === 'order')
    const gateIdx = segments.findIndex(s => s.stage === 'gate')
    expect(orderIdx).toBeLessThan(gateIdx)
  })

  // Test 19: Prototype pollution with valid fallback
  it('silently ignores __proto__/constructor/hasOwnProperty stage names, preserves valid stages', () => {
    const events = [
      { stage: '__proto__', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'constructor', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'hasOwnProperty', status: 'passed', detail: '', timestamp: new Date().toISOString() },
      { stage: 'claimed', status: 'passed', detail: 'valid', timestamp: new Date().toISOString() }
    ]
    const segments = deriveSegments(events)
    expect(Object.prototype.polluted).toBeUndefined()
    expect(segments.length).toBe(1)
    expect(segments[0].stage).toBe('claimed')
  })

  // Test 20: determinism with pinned now
  it('deterministically detects stalled status with pinned now timestamp', () => {
    const fixedNow = 1000000
    const oldTime = new Date(fixedNow - 35 * 60000).toISOString()
    const recentTime = new Date(fixedNow - 5 * 60000).toISOString()
    const events1 = [
      { stage: 'claimed', status: 'started', timestamp: oldTime }
    ]
    const events2 = [
      { stage: 'claimed', status: 'started', timestamp: recentTime }
    ]
    const seg1 = deriveSegments(events1, { now: fixedNow, isLiveNow: true, stallMinutes: 30 })
    const seg2 = deriveSegments(events2, { now: fixedNow, isLiveNow: true, stallMinutes: 30 })
    expect(seg1[0].status).toBe('stalled')
    expect(seg2[0].status).toBe('started')
  })

  // Test 25: Prototype pollution resistance - updated version
  it('does not allow prototype pollution and silently ignores invalid stages', () => {
    const events = [
      { stage: '__proto__', status: 'passed', detail: '' },
      { stage: 'constructor', status: 'passed', detail: '' },
      { stage: 'hasOwnProperty', status: 'passed', detail: '' }
    ]
    deriveSegments(events)
    expect(Object.prototype.polluted).toBeUndefined()
    expect((new Map()).get('__proto__')).toBeUndefined() // Map unaffected
  })
})
