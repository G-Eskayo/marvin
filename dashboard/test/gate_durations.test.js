import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  DEFAULT_TEST_TIMEOUT_MS,
  GATE_TIMEOUT_CEILING_MS,
  GATE_OVERHEAD_MS,
  recordDuration,
  recentPassingDurations,
  median,
  countConcurrentPytest,
  sizedStepTimeouts,
  computeGateTimeoutMs
} from '../webhook-server/gate_durations.js'

describe('gate_durations', () => {
  // Test 1: recordDuration creates a valid log entry
  it('recordDuration writes a JSON line with step, ms, and passed fields', () => {
    const lines = []
    const append = (file, line) => lines.push(line)
    const now = () => 1609459200000 // Fixed time for testing

    const result = recordDuration({ step: 'pytest', ms: 5432, passed: true }, append, now)

    expect(result).toEqual({
      t: '2021-01-01T00:00:00.000Z',
      kind: 'duration',
      step: 'pytest',
      ms: 5432,
      passed: true
    })
    expect(lines).toHaveLength(1)
    expect(JSON.parse(lines[0])).toMatchObject({ step: 'pytest', ms: 5432, passed: true })
  })

  // Test 2: recordDuration with passed=false
  it('records failed test runs', () => {
    const lines = []
    const append = (file, line) => lines.push(line)

    recordDuration({ step: 'vitest', ms: 3000, passed: false }, append)

    expect(JSON.parse(lines[0])).toMatchObject({ step: 'vitest', passed: false })
  })

  // Test 3: recordDuration handles non-numeric ms values
  it('coerces ms to integer', () => {
    const lines = []
    const append = (file, line) => lines.push(line)

    recordDuration({ step: 'pytest', ms: 1234.567, passed: true }, append)

    expect(JSON.parse(lines[0]).ms).toBe(1235)
  })

  // Test 4: recordDuration fails gracefully
  it('returns null on append error', () => {
    const append = () => { throw new Error('write failed') }
    const result = recordDuration({ step: 'pytest', ms: 1000, passed: true }, append)

    expect(result).toBeNull()
  })

  // Test 5: recentPassingDurations returns empty list when file missing
  it('recentPassingDurations returns empty when file does not exist', () => {
    const readFile = () => []
    const result = recentPassingDurations('pytest', 'nonexistent.jsonl', 10, readFile)

    expect(result).toEqual([])
  })

  // Test 6: recentPassingDurations filters by step and passed=true
  it('returns only passing durations for the given step', () => {
    const logLines = [
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1000000, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1500000, passed: false }),
      JSON.stringify({ kind: 'duration', step: 'vitest', ms: 2000000, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 900000, passed: true })
    ]
    const readFile = () => logLines

    const result = recentPassingDurations('pytest', 'test.jsonl', 10, readFile)

    expect(result).toEqual([1000000, 900000])
  })

  // Test 7: recentPassingDurations respects limit
  it('returns only the most recent N durations', () => {
    const logLines = Array.from({ length: 20 }, (_, i) =>
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1000000 + i * 100000, passed: true })
    )
    const readFile = () => logLines

    const result = recentPassingDurations('pytest', 'test.jsonl', 5, readFile)

    expect(result).toHaveLength(5)
    // Last 5 elements: indices 15-19 with ms = 2500000, 2600000, 2700000, 2800000, 2900000
    expect(result).toEqual([2500000, 2600000, 2700000, 2800000, 2900000])
  })

  // Test 8: recentPassingDurations handles malformed JSON
  it('ignores malformed JSON lines', () => {
    const logLines = [
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1000, passed: true }),
      'not json',
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1100, passed: true })
    ]
    const readFile = () => logLines

    const result = recentPassingDurations('pytest', 'test.jsonl', 10, readFile)

    expect(result).toEqual([1000, 1100])
  })

  // Test 9: median of empty list
  it('median returns 0 for empty list', () => {
    expect(median([])).toBe(0)
  })

  // Test 10: median of odd-length list
  it('median returns middle element for odd-length list', () => {
    expect(median([1, 2, 3, 4, 5])).toBe(3)
  })

  // Test 11: median of even-length list
  it('median returns average of middle two for even-length list', () => {
    expect(median([1, 2, 3, 4])).toBe(2.5)
  })

  // Test 12: median with unsorted input
  it('median works with unsorted input', () => {
    expect(median([5, 1, 3, 2, 4])).toBe(3)
  })

  // Test 13: countConcurrentPytest returns 0 by default
  it('countConcurrentPytest returns 0 by default', () => {
    expect(countConcurrentPytest()).toBe(0)
  })

  // Test 14: sizedStepTimeouts with no history
  it('sizedStepTimeouts returns DEFAULT_TEST_TIMEOUT_MS when no history exists', () => {
    const readFile = () => []
    const result = sizedStepTimeouts(['pytest', 'vitest'], readFile)

    expect(result).toEqual({
      pytest: DEFAULT_TEST_TIMEOUT_MS,
      vitest: DEFAULT_TEST_TIMEOUT_MS
    })
  })

  // Test 15: sizedStepTimeouts computes 1.5x median
  it('sizedStepTimeouts computes timeouts as 1.5x median of recent durations', () => {
    const logLines = [
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1000000, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1200000, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 1100000, passed: true })
    ]
    const readFile = () => logLines
    const result = sizedStepTimeouts(['pytest'], readFile)

    // median = 1100000, timeout = 1100000 * 1.5 = 1650000
    expect(result.pytest).toBe(1650000)
  })

  // Test 16: sizedStepTimeouts enforces minimum timeout
  it('sizedStepTimeouts enforces DEFAULT_TEST_TIMEOUT_MS minimum', () => {
    const logLines = [
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 100, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 200, passed: true })
    ]
    const readFile = () => logLines
    const result = sizedStepTimeouts(['pytest'], readFile)

    expect(result.pytest).toBe(DEFAULT_TEST_TIMEOUT_MS)
  })

  // Test 17: sizedStepTimeouts handles multiple steps
  it('sizedStepTimeouts returns all requested steps', () => {
    const logLines = [
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 2000000, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'vitest', ms: 3000000, passed: true })
    ]
    const readFile = () => logLines
    const result = sizedStepTimeouts(['pytest', 'vitest'], readFile)

    expect(result).toHaveProperty('pytest')
    expect(result).toHaveProperty('vitest')
  })

  // Test 18: computeGateTimeoutMs with no history
  it('computeGateTimeoutMs returns default timeouts + overhead when no history exists', () => {
    const readFile = () => []
    const result = computeGateTimeoutMs(['pytest', 'vitest'], readFile)

    // No history: each step gets DEFAULT_TEST_TIMEOUT_MS, plus overhead
    const expected = DEFAULT_TEST_TIMEOUT_MS * 2 + GATE_OVERHEAD_MS
    // Expected will be capped at GATE_TIMEOUT_CEILING_MS if it exceeds it
    const capped = Math.min(expected, GATE_TIMEOUT_CEILING_MS)
    expect(result).toBe(capped)
  })

  // Test 19: computeGateTimeoutMs sums step timeouts with overhead
  it('computeGateTimeoutMs sums step timeouts and adds GATE_OVERHEAD_MS', () => {
    const logLines = [
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 500000, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'vitest', ms: 600000, passed: true })
    ]
    const readFile = () => logLines
    const result = computeGateTimeoutMs(['pytest', 'vitest'], readFile)

    // Both below minimum, so max(1200000, 750000) + max(1200000, 900000) = 1200000 + 1200000 + 300000 = 2700000, capped at ceiling
    const expected = Math.min(DEFAULT_TEST_TIMEOUT_MS * 2 + GATE_OVERHEAD_MS, GATE_TIMEOUT_CEILING_MS)
    expect(result).toBe(expected)
  })

  // Test 20: computeGateTimeoutMs enforces ceiling
  it('computeGateTimeoutMs never exceeds GATE_TIMEOUT_CEILING_MS', () => {
    const logLines = [
      JSON.stringify({ kind: 'duration', step: 'pytest', ms: 20000, passed: true }),
      JSON.stringify({ kind: 'duration', step: 'verify:big-repo', ms: 25000, passed: true })
    ]
    const readFile = () => logLines
    const result = computeGateTimeoutMs(['pytest', 'verify:big-repo'], readFile)

    expect(result).toBeLessThanOrEqual(GATE_TIMEOUT_CEILING_MS)
  })

  // Test 21: Constants have reasonable values
  it('constants have expected values', () => {
    expect(DEFAULT_TEST_TIMEOUT_MS).toBe(1200_000) // 20 minutes
    expect(GATE_TIMEOUT_CEILING_MS).toBe(40 * 60_000) // 40 minutes
    expect(GATE_OVERHEAD_MS).toBe(5 * 60_000) // 5 minutes
  })
})
