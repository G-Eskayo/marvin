import { describe, it, expect } from 'vitest'
import {
  DEFAULT_TEST_TIMEOUT_MS,
  GATE_TIMEOUT_CEILING_MS,
  GATE_OVERHEAD_MS,
  recordDuration,
  recentPassingDurations,
  median,
  sizedTimeoutMs,
  sizedStepTimeouts,
  computeGateTimeoutMs,
  countConcurrentPytest
} from '../webhook-server/gate_durations.js'

describe('gate_durations', () => {
  // Test 1: recordDuration writes a record to the log
  it('recordDuration writes a JSON line with timestamp and duration', () => {
    const records = []
    const append = (file, line) => records.push(JSON.parse(line))
    const now = () => new Date('2026-10-17T12:00:00Z')

    recordDuration({ label: 'pytest', durationMs: 50_000 }, append, now)

    expect(records).toHaveLength(1)
    expect(records[0]).toMatchObject({
      t: '2026-10-17T12:00:00.000Z',
      label: 'pytest',
      durationMs: 50_000
    })
  })

  // Test 2: recordDuration includes countConcurrent when provided
  it('recordDuration includes countConcurrent when present', () => {
    const records = []
    const append = (file, line) => records.push(JSON.parse(line))

    recordDuration({ label: 'pytest', durationMs: 60_000, countConcurrent: 4 }, append)

    expect(records[0].countConcurrent).toBe(4)
  })

  // Test 3: recordDuration omits countConcurrent when undefined
  it('recordDuration omits countConcurrent when undefined', () => {
    const records = []
    const append = (file, line) => records.push(JSON.parse(line))

    recordDuration({ label: 'pytest', durationMs: 60_000 }, append)

    expect(records[0]).not.toHaveProperty('countConcurrent')
  })

  // Test 4: recordDuration returns null on write failure
  it('recordDuration fails gracefully on append error', () => {
    const badAppend = () => { throw new Error('write failed') }
    const result = recordDuration({ label: 'pytest', durationMs: 50_000 }, badAppend)

    expect(result).toBeNull()
  })

  // Test 5: recentPassingDurations extracts all durations for a label
  it('recentPassingDurations extracts all matching durations', () => {
    const logContent = [
      '{"t":"2026-10-17T12:00:00Z","label":"pytest","durationMs":50000}',
      '{"t":"2026-10-17T12:01:00Z","label":"pytest","durationMs":55000}',
      '{"t":"2026-10-17T12:02:00Z","label":"vitest","durationMs":30000}',
      '{"t":"2026-10-17T12:03:00Z","label":"pytest","durationMs":52000}'
    ].join('\n')
    const read = () => logContent

    const durations = recentPassingDurations('pytest', '', read)

    expect(durations).toEqual([50_000, 55_000, 52_000])
  })

  // Test 6: recentPassingDurations handles empty log
  it('recentPassingDurations returns empty array for empty log', () => {
    const read = () => ''
    const durations = recentPassingDurations('pytest', '', read)
    expect(durations).toEqual([])
  })

  // Test 7: recentPassingDurations ignores malformed lines
  it('recentPassingDurations ignores malformed JSON lines', () => {
    const logContent = [
      '{"t":"2026-10-17T12:00:00Z","label":"pytest","durationMs":50000}',
      'not json',
      '{"t":"2026-10-17T12:01:00Z","label":"pytest","durationMs":55000}'
    ].join('\n')
    const read = () => logContent

    const durations = recentPassingDurations('pytest', '', read)

    expect(durations).toEqual([50_000, 55_000])
  })

  // Test 8: median of odd-length array
  it('median of odd-length array returns the middle value', () => {
    const result = median([10, 20, 30, 40, 50])
    expect(result).toBe(30)
  })

  // Test 9: median of even-length array
  it('median of even-length array returns average of middle two', () => {
    const result = median([10, 20, 30, 40])
    expect(result).toBe(25)
  })

  // Test 10: median of single value
  it('median of single value returns that value', () => {
    const result = median([42])
    expect(result).toBe(42)
  })

  // Test 11: median of empty array
  it('median of empty array returns null', () => {
    const result = median([])
    expect(result).toBeNull()
  })

  // Test 12: median of null
  it('median of null returns null', () => {
    const result = median(null)
    expect(result).toBeNull()
  })

  // Test 13: sizedTimeoutMs with no history returns minMs
  it('sizedTimeoutMs returns minMs when no history exists', () => {
    const read = () => ''
    const result = sizedTimeoutMs('pytest', { minMs: 600_000 }, '', read)
    expect(result).toBe(600_000)
  })

  // Test 14: sizedTimeoutMs applies concurrency factor
  it('sizedTimeoutMs multiplies median by concurrencyFactor', () => {
    const logContent = '{"t":"2026-10-17T12:00:00Z","label":"pytest","durationMs":500000}'
    const read = () => logContent
    const result = sizedTimeoutMs(
      'pytest',
      { minMs: 100_000, concurrencyFactor: 2.0, historySamples: 10 },
      '',
      read
    )
    expect(result).toBe(1_000_000)
  })

  // Test 15: sizedTimeoutMs respects maxMs ceiling
  it('sizedTimeoutMs caps at maxMs', () => {
    const logContent = '{"t":"2026-10-17T12:00:00Z","label":"pytest","durationMs":50000000}'
    const read = () => logContent
    const result = sizedTimeoutMs(
      'pytest',
      { minMs: 600_000, maxMs: 1_000_000 },
      '',
      read
    )
    expect(result).toBe(1_000_000)
  })

  // Test 16: sizedStepTimeouts computes per-step timeouts
  it('sizedStepTimeouts returns a map of step to timeout', () => {
    const logContent = [
      '{"t":"2026-10-17T12:00:00Z","label":"pytest","durationMs":50000}',
      '{"t":"2026-10-17T12:01:00Z","label":"vitest","durationMs":30000}'
    ].join('\n')
    const read = () => logContent
    const result = sizedStepTimeouts(['pytest', 'vitest'], { minMs: 600_000 }, '', read)

    expect(result).toHaveProperty('pytest')
    expect(result).toHaveProperty('vitest')
  })

  // Test 17: computeGateTimeoutMs sums max step timeout and overhead
  it('computeGateTimeoutMs adds overhead to the max step timeout', () => {
    const logContent = '{"t":"2026-10-17T12:00:00Z","label":"pytest","durationMs":100000}'
    const read = () => logContent
    const result = computeGateTimeoutMs(['pytest'], { minMs: 100_000, maxMs: 2000_000 }, '', read)

    // sized = 100_000 * 1.5 (default factor) = 150_000
    // maxGateMs = max(DEFAULT_TEST_TIMEOUT_MS, 150_000) = DEFAULT_TEST_TIMEOUT_MS = 1_200_000
    // total = 1_200_000 + GATE_OVERHEAD_MS
    expect(result).toBe(DEFAULT_TEST_TIMEOUT_MS + GATE_OVERHEAD_MS)
  })

  // Test 18: computeGateTimeoutMs respects ceiling
  it('computeGateTimeoutMs never exceeds GATE_TIMEOUT_CEILING_MS', () => {
    const logContent = '{"t":"2026-10-17T12:00:00Z","label":"pytest","durationMs":50000000}'
    const read = () => logContent
    const result = computeGateTimeoutMs(['pytest'], { maxMs: 50000000 }, '', read)

    expect(result).toBeLessThanOrEqual(GATE_TIMEOUT_CEILING_MS)
  })

  // Test 19: countConcurrentPytest extracts max concurrent from recent logs
  it('countConcurrentPytest returns max concurrency in recent window', () => {
    const now = new Date('2026-10-17T12:05:00Z')
    const logContent = [
      `{"t":"2026-10-17T12:04:00Z","label":"pytest","countConcurrent":2}`,
      `{"t":"2026-10-17T12:04:30Z","label":"pytest","countConcurrent":4}`,
      `{"t":"2026-10-17T12:02:00Z","label":"pytest","countConcurrent":8}`  // older than window
    ].join('\n')
    const read = () => logContent
    const result = countConcurrentPytest(() => now, '', read)

    expect(result).toBe(4)
  })
})
