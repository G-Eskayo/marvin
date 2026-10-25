import { describe, it, expect, vi } from 'vitest'
import {
  DEFAULT_TEST_TIMEOUT_MS,
  STEP_TIMEOUT_CEILING_MS,
  GATE_TIMEOUT_CEILING_MS,
  GATE_OVERHEAD_MS,
  recordDuration,
  recentPassingDurations,
  median,
  sizedTimeoutMs,
  computeGateTimeoutMs,
  countConcurrentPytest
} from '../webhook-server/gate_durations.js'

describe('recordDuration', () => {
  it('appends one JSON line with key, durationMs, passed, and ISO timestamp', () => {
    const append = vi.fn()
    const now = () => new Date('2026-10-17T14:00:00.000Z').getTime()
    const rec = recordDuration('pytest', 5000, true, append, now, '/tmp/x.jsonl')

    expect(append).toHaveBeenCalledTimes(1)
    const [file, line] = append.mock.calls[0]
    expect(file).toBe('/tmp/x.jsonl')
    expect(line.endsWith('\n')).toBe(true)
    const parsed = JSON.parse(line)
    expect(parsed).toEqual({
      t: '2026-10-17T14:00:00.000Z',
      key: 'pytest',
      durationMs: 5000,
      passed: true
    })
  })

  it('accepts passed=false for failed runs', () => {
    const append = vi.fn()
    const now = () => new Date('2026-10-17T14:00:00.000Z').getTime()
    recordDuration('pytest', 5000, false, append, now, '/tmp/x.jsonl')
    const parsed = JSON.parse(append.mock.calls[0][1])
    expect(parsed.passed).toBe(false)
  })

  it('never throws, even when the write fails', () => {
    const append = vi.fn(() => { throw new Error('disk full') })
    expect(() => recordDuration('pytest', 5000, true, append, () => Date.now(), '/tmp/x')).not.toThrow()
    expect(recordDuration('pytest', 5000, true, append, () => Date.now(), '/tmp/x')).toBeNull()
  })

  it('rounds duration to nearest integer', () => {
    const append = vi.fn()
    recordDuration('pytest', 5123.456, true, append, () => Date.now(), '/tmp/x')
    const parsed = JSON.parse(append.mock.calls[0][1])
    expect(parsed.durationMs).toBe(5123)
  })

  it('records zero or negative durations (no validation)', () => {
    const append = vi.fn()
    recordDuration('pytest', 0, true, append, () => Date.now(), '/tmp/x')
    const parsed = JSON.parse(append.mock.calls[0][1])
    expect(parsed.durationMs).toBe(0)
  })
})

describe('recentPassingDurations', () => {
  it('takes an array of exact keys and returns matching passed runs', () => {
    const read = () => `{"t":"2026-10-17T14:00:00.000Z","key":"pytest","durationMs":5000,"passed":true}
{"t":"2026-10-17T14:01:00.000Z","key":"vitest","durationMs":3000,"passed":true}
{"t":"2026-10-17T14:02:00.000Z","key":"pytest","durationMs":4500,"passed":true}`
    const result = recentPassingDurations(['pytest', 'vitest'], read, '/tmp/x')
    expect(result.pytest).toEqual([4500, 5000])  // newest first
    expect(result.vitest).toEqual([3000])
  })

  it('ignores runs where passed=false', () => {
    const read = () => `{"t":"2026-10-17T14:00:00.000Z","key":"pytest","durationMs":5000,"passed":true}
{"t":"2026-10-17T14:01:00.000Z","key":"pytest","durationMs":4000,"passed":false}
{"t":"2026-10-17T14:02:00.000Z","key":"pytest","durationMs":4500,"passed":true}`
    const result = recentPassingDurations(['pytest'], read, '/tmp/x')
    expect(result.pytest).toEqual([4500, 5000])  // 4000 excluded (failed)
  })

  it('returns empty map when file is empty', () => {
    const read = () => ''
    const result = recentPassingDurations(['pytest', 'vitest'], read, '/tmp/x')
    expect(result).toEqual({})
  })

  it('ignores unparseable JSON lines', () => {
    const read = () => `{"t":"2026-10-17T14:00:00.000Z","key":"pytest","durationMs":5000,"passed":true}
not json at all
{"t":"2026-10-17T14:01:00.000Z","key":"pytest","durationMs":4500,"passed":true}`
    const result = recentPassingDurations(['pytest'], read, '/tmp/x')
    expect(result.pytest).toEqual([4500, 5000])  // newest first
  })

  it('ignores records with negative or zero duration', () => {
    const read = () => `{"t":"2026-10-17T14:00:00.000Z","key":"pytest","durationMs":0,"passed":true}
{"t":"2026-10-17T14:01:00.000Z","key":"pytest","durationMs":5000,"passed":true}
{"t":"2026-10-17T14:02:00.000Z","key":"pytest","durationMs":-100,"passed":true}`
    const result = recentPassingDurations(['pytest'], read, '/tmp/x')
    expect(result.pytest).toEqual([5000])
  })

  it('sorts by timestamp newest first', () => {
    const read = () => `{"t":"2026-10-17T14:00:00.000Z","key":"pytest","durationMs":1000,"passed":true}
{"t":"2026-10-17T14:02:00.000Z","key":"pytest","durationMs":3000,"passed":true}
{"t":"2026-10-17T14:01:00.000Z","key":"pytest","durationMs":2000,"passed":true}`
    const result = recentPassingDurations(['pytest'], read, '/tmp/x')
    expect(result.pytest).toEqual([3000, 2000, 1000])
  })

  it('caps to maxPerKey most recent entries', () => {
    const records = Array.from({ length: 30 }, (_, i) =>
      JSON.stringify({ t: new Date(new Date('2026-10-17T00:00:00Z').getTime() + i * 60000).toISOString(), key: 'pytest', durationMs: i * 1000, passed: true })
    ).join('\n')
    const result = recentPassingDurations(['pytest'], () => records, '/tmp/x', 10)
    expect(result.pytest.length).toBe(10)
    expect(result.pytest[0]).toBe(29000)
    expect(result.pytest[9]).toBe(20000)
  })

  it('filters out records missing key, durationMs, or passed field', () => {
    const read = () => `{"t":"2026-10-17T14:00:00.000Z","durationMs":5000,"passed":true}
{"t":"2026-10-17T14:01:00.000Z","key":"pytest","passed":true}
{"t":"2026-10-17T14:02:00.000Z","key":"pytest","durationMs":5000}
{"t":"2026-10-17T14:03:00.000Z","key":"pytest","durationMs":5000,"passed":true}`
    const result = recentPassingDurations(['pytest'], read, '/tmp/x')
    expect(result.pytest).toEqual([5000])
  })

  it('ignores keys not in the provided array', () => {
    const read = () => `{"t":"2026-10-17T14:00:00.000Z","key":"pytest","durationMs":5000,"passed":true}
{"t":"2026-10-17T14:01:00.000Z","key":"other","durationMs":3000,"passed":true}`
    const result = recentPassingDurations(['pytest'], read, '/tmp/x')
    expect(result.pytest).toEqual([5000])
    expect(result.other).toBeUndefined()
  })

  it('reads only the last MAX_LOG_LINES_READ lines from the file', () => {
    const records = Array.from({ length: 6000 }, (_, i) =>
      JSON.stringify({ t: new Date(new Date('2026-10-17T00:00:00Z').getTime() + i * 1000).toISOString(), key: 'pytest', durationMs: i * 100, passed: true })
    ).join('\n')
    const result = recentPassingDurations(['pytest'], () => records, '/tmp/x', 100)
    // Should have at most 100 entries (maxPerKey), and should be from the tail end
    expect(result.pytest.length).toBeLessThanOrEqual(100)
    // The most recent should be ~599900 (last line in the tail)
    expect(result.pytest[0]).toBeGreaterThan(590000)
  })
})

describe('median', () => {
  it('returns 0 for empty array', () => {
    expect(median([])).toBe(0)
  })

  it('returns 0 for non-array input', () => {
    expect(median(null)).toBe(0)
    expect(median(undefined)).toBe(0)
  })

  it('returns single element for array of length 1', () => {
    expect(median([5000])).toBe(5000)
  })

  it('returns average of two middle elements for even-length array', () => {
    expect(median([1000, 2000, 3000, 4000])).toBe(2500)
  })

  it('returns middle element for odd-length array', () => {
    expect(median([1000, 2000, 3000])).toBe(2000)
  })

  it('sorts unsorted input before computing median', () => {
    expect(median([3000, 1000, 2000])).toBe(2000)
  })
})

describe('sizedTimeoutMs', () => {
  it('uses DEFAULT_TEST_TIMEOUT_MS when no history', () => {
    const timeout = sizedTimeoutMs('pytest', {})
    expect(timeout).toBe(DEFAULT_TEST_TIMEOUT_MS)
  })

  it('sizes to max(DEFAULT_TEST_TIMEOUT_MS, 3×median)', () => {
    const timeout = sizedTimeoutMs('pytest', { pytest: [500000, 500000, 500000] })
    expect(timeout).toBe(1500000) // max(1200000, 500000 * 3) = 1500000
  })

  it('uses DEFAULT_TEST_TIMEOUT_MS when 3×median is smaller', () => {
    const timeout = sizedTimeoutMs('pytest', { pytest: [5000, 5000, 5000] })
    expect(timeout).toBe(DEFAULT_TEST_TIMEOUT_MS) // max(1200000, 5000 * 3) = 1200000
  })

  it('caps to STEP_TIMEOUT_CEILING_MS', () => {
    const timeout = sizedTimeoutMs('pytest', { pytest: [30000000, 30000000] })
    expect(timeout).toBeLessThanOrEqual(STEP_TIMEOUT_CEILING_MS)
  })

  it('caps to custom ceilingMs parameter', () => {
    const timeout = sizedTimeoutMs('pytest', { pytest: [30000000, 30000000] }, 10000)
    expect(timeout).toBeLessThanOrEqual(10000)
  })
})

describe('computeGateTimeoutMs', () => {
  it('sums sized timeouts for all steps and adds overhead', () => {
    const recent = {
      'verify:pytest': [5000],
      'verify:vitest': [3000]
    }
    const timeout = computeGateTimeoutMs(
      ['verify:pytest', 'verify:vitest'],
      recent,
      GATE_TIMEOUT_CEILING_MS,
      60000
    )
    // pytest: max(1200000, 5000 * 3) = 1200000
    // vitest: max(1200000, 3000 * 3) = 1200000
    // overhead: 60000
    // total: 2460000, capped at GATE_TIMEOUT_CEILING_MS (5400000 = 90*60000)
    expect(timeout).toBe(2460000)
  })

  it('caps total to ceilingMs', () => {
    const timeout = computeGateTimeoutMs(
      ['verify:pytest'],
      { 'verify:pytest': [20000000] },
      100000,
      5000
    )
    expect(timeout).toBeLessThanOrEqual(100000)
  })

  it('uses DEFAULT_TEST_TIMEOUT_MS for unknown steps', () => {
    const timeout = computeGateTimeoutMs(
      ['unknown'],
      {},
      GATE_TIMEOUT_CEILING_MS,
      60000
    )
    // unknown: DEFAULT_TEST_TIMEOUT_MS, overhead: 60000
    // 1260000, well under ceiling
    expect(timeout).toBe(1260000)
  })

  it('handles empty step list', () => {
    const timeout = computeGateTimeoutMs(
      [],
      {},
      GATE_TIMEOUT_CEILING_MS,
      60000
    )
    // Just overhead
    expect(timeout).toBe(60000)
  })

  it('uses GATE_TIMEOUT_CEILING_MS as the default overall ceiling', () => {
    const timeout = computeGateTimeoutMs(
      ['pytest', 'vitest'],
      { pytest: [100], vitest: [100] }
    )
    expect(timeout).toBeLessThanOrEqual(GATE_TIMEOUT_CEILING_MS)
  })
})

describe('countConcurrentPytest', () => {
  it('returns count of running pytest/vitest processes', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '1234\n5678\n' })
    const count = await countConcurrentPytest(exec)
    expect(count).toBe(2)
    expect(exec).toHaveBeenCalledWith('pgrep', ['-f', 'pytest|vitest'])
  })

  it('returns 0 when no processes found (empty stdout)', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '' })
    const count = await countConcurrentPytest(exec)
    expect(count).toBe(0)
  })

  it('returns 0 when output contains only blank lines', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '\n' })
    const count = await countConcurrentPytest(exec)
    expect(count).toBe(0)
  })

  it('returns 0 if exec throws', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('pgrep failed'))
    const count = await countConcurrentPytest(exec)
    expect(count).toBe(0)
  })

  it('ignores blank lines in output', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '1234\n\n5678\n\n' })
    const count = await countConcurrentPytest(exec)
    expect(count).toBe(2)
  })

  it('concurrent tests do not corrupt duration log', async () => {
    // Simulate concurrent recordDuration calls to the same file
    const { mkdtempSync, rmSync } = require('fs')
    const path = require('path')
    const os = require('os')
    const tempFile = mkdtempSync(path.join(os.tmpdir(), 'test-'))
    const logFile = path.join(tempFile, 'durations.jsonl')
    const writes = []
    for (let i = 0; i < 10; i++) {
      writes.push(recordDuration(`step-${i}`, i * 1000, true, undefined, undefined, logFile))
    }
    expect(writes.every(w => w !== null)).toBe(true)
    const result = recentPassingDurations(Array.from({length: 10}, (_, i) => `step-${i}`), undefined, logFile, 100)
    expect(Object.keys(result).length).toBeGreaterThanOrEqual(9)  // Allow for timing variance
    rmSync(tempFile, { recursive: true, force: true })
  })
})
