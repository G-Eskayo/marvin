import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import path from 'path'
import os from 'os'
import {
  DEFAULT_TEST_TIMEOUT_MS,
  GATE_TIMEOUT_CEILING_MS,
  recordDuration,
  recentPassingDurations,
  median,
  sizedTimeoutMs,
  countConcurrentPytest,
  computeGateTimeoutMs
} from '../webhook-server/gate_durations.js'

let tempDir

beforeEach(() => {
  tempDir = mkdtempSync(path.join(os.tmpdir(), 'gate-durations-test-'))
})

afterEach(() => {
  try {
    rmSync(tempDir, { recursive: true, force: true })
  } catch {}
})

describe('gate_durations', () => {
  // Test 1: DEFAULT_TEST_TIMEOUT_MS is exported
  it('exports DEFAULT_TEST_TIMEOUT_MS', () => {
    expect(DEFAULT_TEST_TIMEOUT_MS).toBe(1200_000)
  })

  // Test 2: GATE_TIMEOUT_CEILING_MS is exported
  it('exports GATE_TIMEOUT_CEILING_MS', () => {
    expect(GATE_TIMEOUT_CEILING_MS).toBe(40 * 60_000)
  })

  // Test 3: recordDuration writes to the log
  it('recordDuration appends an entry to the log', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 500, { logPath })
    recordDuration('pytest', 600, { logPath })

    const durations = recentPassingDurations('pytest', { logPath })
    expect(durations).toEqual([500, 600])
  })

  // Test 4: recordDuration marks success by default
  it('recordDuration marks success by default', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('vitest', 1000, { logPath })

    const durations = recentPassingDurations('vitest', { logPath })
    expect(durations).toEqual([1000])
  })

  // Test 5: recordDuration honors success option
  it('recordDuration honors success option', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 500, { logPath, success: true })
    recordDuration('pytest', 600, { logPath, success: false })

    const durations = recentPassingDurations('pytest', { logPath })
    expect(durations).toEqual([500])
  })

  // Test 6: recentPassingDurations filters by test type
  it('recentPassingDurations filters by test type', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 500, { logPath })
    recordDuration('vitest', 300, { logPath })
    recordDuration('pytest', 600, { logPath })

    expect(recentPassingDurations('pytest', { logPath })).toEqual([500, 600])
    expect(recentPassingDurations('vitest', { logPath })).toEqual([300])
  })

  // Test 7: recentPassingDurations respects limit
  it('recentPassingDurations respects limit option', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    for (let i = 0; i < 10; i++) {
      recordDuration('pytest', 100 * (i + 1), { logPath })
    }

    const durations = recentPassingDurations('pytest', { logPath, limit: 3 })
    expect(durations).toHaveLength(3)
    expect(durations).toEqual([800, 900, 1000])
  })

  // Test 8: recentPassingDurations handles empty log
  it('recentPassingDurations returns empty array for nonexistent log', () => {
    const logPath = path.join(tempDir, 'nonexistent.jsonl')
    expect(recentPassingDurations('pytest', { logPath })).toEqual([])
  })

  // Test 9: median of odd-length array
  it('median of odd-length array returns middle element', () => {
    expect(median([1, 2, 3])).toBe(2)
  })

  // Test 10: median of even-length array
  it('median of even-length array returns average', () => {
    expect(median([1, 2, 3, 4])).toBe(2.5) // average of 2 and 3
  })

  // Test 11: median handles unsorted array
  it('median sorts array internally', () => {
    expect(median([5, 1, 3])).toBe(3)
  })

  // Test 12: median of empty array
  it('median returns DEFAULT_TEST_TIMEOUT_MS for empty array', () => {
    expect(median([])).toBe(DEFAULT_TEST_TIMEOUT_MS)
  })

  // Test 13: median of null
  it('median returns DEFAULT_TEST_TIMEOUT_MS for null', () => {
    expect(median(null)).toBe(DEFAULT_TEST_TIMEOUT_MS)
  })

  // Test 14: sizedTimeoutMs with no history
  it('sizedTimeoutMs returns DEFAULT_TEST_TIMEOUT_MS when no history', () => {
    const logPath = path.join(tempDir, 'empty.jsonl')
    const sized = sizedTimeoutMs('pytest', { logPath })
    expect(sized).toBe(DEFAULT_TEST_TIMEOUT_MS)
  })

  // Test 15: sizedTimeoutMs applies multiplier
  it('sizedTimeoutMs applies multiplier to median', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 1000, { logPath })

    const sized = sizedTimeoutMs('pytest', { logPath, multiplier: 2 })
    expect(sized).toBe(2000)
  })

  // Test 16: sizedTimeoutMs respects cap
  it('sizedTimeoutMs respects capMs', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 1000, { logPath })

    const sized = sizedTimeoutMs('pytest', { logPath, capMs: 500, multiplier: 2 })
    expect(sized).toBe(500)
  })

  // Test 17: sizedTimeoutMs with multiple durations
  it('sizedTimeoutMs uses median of recent durations', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 1000, { logPath })
    recordDuration('pytest', 1200, { logPath })
    recordDuration('pytest', 1400, { logPath })

    const sized = sizedTimeoutMs('pytest', { logPath, multiplier: 1.5 })
    expect(sized).toBe(1800) // median(1000, 1200, 1400) = 1200, * 1.5 = 1800
  })

  // Test 18: countConcurrentPytest handles exec errors
  it('countConcurrentPytest returns 1 on exec error', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('pytest not found'))
    const count = await countConcurrentPytest(exec)
    expect(count).toBe(1)
  })

  // Test 19: countConcurrentPytest calculates from test count
  it('countConcurrentPytest calculates concurrency from test count', async () => {
    const exec = vi.fn().mockResolvedValue({
      stdout: Array(100).fill('test_name').join('\n')
    })
    const count = await countConcurrentPytest(exec)
    expect(count).toBe(Math.max(1, Math.ceil(100 / 10)))
  })

  // Test 20: computeGateTimeoutMs returns a reasonable value
  it('computeGateTimeoutMs returns a reasonable value', () => {
    const timeout = computeGateTimeoutMs()
    expect(timeout).toBeGreaterThan(0)
    expect(timeout).toBeLessThanOrEqual(GATE_TIMEOUT_CEILING_MS)
  })

  // Test 21: computeGateTimeoutMs uses provided caps
  it('computeGateTimeoutMs respects pytestCapMs', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 100_000, { logPath })
    recordDuration('vitest', 100_000, { logPath })

    const timeout = computeGateTimeoutMs({ logPath, pytestCapMs: 50_000, vitestCapMs: 50_000 })
    expect(timeout).toBeLessThanOrEqual(GATE_TIMEOUT_CEILING_MS)
  })

  // Test 22: computeGateTimeoutMs caps at GATE_TIMEOUT_CEILING_MS
  it('computeGateTimeoutMs never exceeds GATE_TIMEOUT_CEILING_MS', () => {
    const timeout = computeGateTimeoutMs({ pytestCapMs: 100_000_000, vitestCapMs: 100_000_000 })
    expect(timeout).toBeLessThanOrEqual(GATE_TIMEOUT_CEILING_MS)
  })

  // Test 23: recordDuration creates log directory if needed
  it('recordDuration creates log directory if needed', () => {
    const logPath = path.join(tempDir, 'subdir', 'subsubdir', 'durations.jsonl')
    recordDuration('pytest', 500, { logPath })

    const durations = recentPassingDurations('pytest', { logPath })
    expect(durations).toEqual([500])
  })

  // Test 24: multiple test types coexist in same log
  it('multiple test types coexist in same log', () => {
    const logPath = path.join(tempDir, 'durations.jsonl')
    recordDuration('pytest', 500, { logPath })
    recordDuration('vitest', 300, { logPath })
    recordDuration('verify:some-repo', 1000, { logPath })
    recordDuration('pytest', 600, { logPath })

    expect(recentPassingDurations('pytest', { logPath })).toEqual([500, 600])
    expect(recentPassingDurations('vitest', { logPath })).toEqual([300])
    expect(recentPassingDurations('verify:some-repo', { logPath })).toEqual([1000])
  })
})
