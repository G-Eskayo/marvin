import { describe, it, expect, vi } from 'vitest'
import {
  recordDuration,
  recentPassingDurations,
  median,
  sizedTimeoutMs,
  countConcurrentPytest,
  DEFAULT_TEST_TIMEOUT_MS
} from '../webhook-server/gate_durations.js'

describe('recordDuration', () => {
  it('records a duration, pass status, and key into a JSON line', () => {
    const lines = []
    const append = (file, line) => lines.push(line)
    const now = () => new Date('2026-10-15T10:00:00Z')

    const result = recordDuration({ key: 'pytest', durationMs: 45000, passed: true }, append, now, '/dev/null')

    expect(result).toMatchObject({ key: 'pytest', durationMs: 45000, passed: true })
    expect(result.t).toBe('2026-10-15T10:00:00.000Z')
    expect(lines[0]).toContain('"key":"pytest"')
    expect(lines[0]).toContain('"durationMs":45000')
    expect(lines[0]).toContain('"passed":true')
  })

  it('records a failed run', () => {
    const lines = []
    const append = (file, line) => lines.push(line)
    const result = recordDuration({ key: 'vitest', durationMs: 60000, passed: false }, append, () => new Date(), '/dev/null')
    expect(result.passed).toBe(false)
  })

  it('rounds duration to an integer', () => {
    const lines = []
    const append = (file, line) => lines.push(line)
    recordDuration({ key: 'pytest', durationMs: 45000.789, passed: true }, append, () => new Date(), '/dev/null')
    expect(lines[0]).toContain('"durationMs":45001')
  })

  it('returns null and does not throw when append fails', () => {
    const append = () => { throw new Error('disk full') }
    const result = recordDuration({ key: 'pytest', durationMs: 45000, passed: true }, append, () => new Date(), '/dev/null')
    expect(result).toBeNull()
  })
})

describe('median', () => {
  it('returns the middle value for odd-length arrays', () => {
    expect(median([1, 2, 3, 4, 5])).toBe(3)
    expect(median([5, 1, 3])).toBe(3)
  })

  it('returns the average of the two middle values for even-length arrays', () => {
    expect(median([1, 2, 3, 4])).toBe(2.5)
    expect(median([10, 20])).toBe(15)
  })

  it('handles single-element arrays', () => {
    expect(median([42])).toBe(42)
  })

  it('returns null for empty arrays', () => {
    expect(median([])).toBeNull()
  })

  it('returns null for non-array input', () => {
    expect(median(null)).toBeNull()
    expect(median(undefined)).toBeNull()
  })

  it('sorts before computing (does not assume input is sorted)', () => {
    expect(median([100, 1, 50])).toBe(50)
  })
})

describe('recentPassingDurations', () => {
  it('returns the median of recent passing runs for a key', () => {
    const records = [
      { key: 'pytest', durationMs: 30000, passed: true, t: '2026-10-15T09:00:00Z' },
      { key: 'pytest', durationMs: 40000, passed: true, t: '2026-10-15T09:10:00Z' },
      { key: 'pytest', durationMs: 50000, passed: true, t: '2026-10-15T09:20:00Z' }
    ]
    const read = () => records
    const result = recentPassingDurations('pytest', { file: '/dev/null', read })
    expect(result).toBe(40000)
  })

  it('ignores failed runs', () => {
    const records = [
      { key: 'pytest', durationMs: 10000, passed: false, t: '2026-10-15T09:00:00Z' },
      { key: 'pytest', durationMs: 40000, passed: true, t: '2026-10-15T09:10:00Z' },
      { key: 'pytest', durationMs: 50000, passed: true, t: '2026-10-15T09:20:00Z' }
    ]
    const read = () => records
    const result = recentPassingDurations('pytest', { file: '/dev/null', read })
    expect(result).toBe(45000)
  })

  it('filters by key (does not mix different test suites)', () => {
    const records = [
      { key: 'pytest', durationMs: 50000, passed: true },
      { key: 'vitest', durationMs: 10000, passed: true },
      { key: 'pytest', durationMs: 40000, passed: true }
    ]
    const read = () => records
    expect(recentPassingDurations('pytest', { file: '/dev/null', read })).toBe(45000)
    expect(recentPassingDurations('vitest', { file: '/dev/null', read })).toBe(10000)
  })

  it('respects the limit parameter (most recent N runs)', () => {
    const records = [
      { key: 'pytest', durationMs: 10000, passed: true },
      { key: 'pytest', durationMs: 20000, passed: true },
      { key: 'pytest', durationMs: 30000, passed: true },
      { key: 'pytest', durationMs: 40000, passed: true }
    ]
    const read = () => records
    // Default limit is 10, so all 4 records are used.
    expect(recentPassingDurations('pytest', { file: '/dev/null', read, limit: 10 })).toBe(25000)
    // With limit 2, only the last 2 are used: 30000 and 40000.
    expect(recentPassingDurations('pytest', { file: '/dev/null', read, limit: 2 })).toBe(35000)
  })

  it('returns null when no passing runs are found', () => {
    const read = () => []
    const result = recentPassingDurations('pytest', { file: '/dev/null', read })
    expect(result).toBeNull()
  })

  it('returns null when only failed runs are found for the key', () => {
    const records = [
      { key: 'pytest', durationMs: 50000, passed: false },
      { key: 'pytest', durationMs: 40000, passed: false }
    ]
    const read = () => records
    expect(recentPassingDurations('pytest', { file: '/dev/null', read })).toBeNull()
  })

  it('returns null and does not throw when read fails', () => {
    const read = () => { throw new Error('io error') }
    const result = recentPassingDurations('pytest', { file: '/dev/null', read })
    expect(result).toBeNull()
  })
})

describe('sizedTimeoutMs', () => {
  const mockRead = (records) => () => records

  it('applies the multiplier to the median duration', () => {
    const records = [
      { key: 'pytest', durationMs: 10000, passed: true },
      { key: 'pytest', durationMs: 20000, passed: true },
      { key: 'pytest', durationMs: 30000, passed: true }
    ]
    // Median is 20000, multiplier is 3 (default), so timeout is 60000.
    const result = sizedTimeoutMs('pytest', {
      file: '/dev/null',
      read: mockRead(records),
      floorMs: 5000,
      capMs: 100000
    })
    expect(result).toBe(60000)
  })

  it('enforces the floor: never goes below floorMs', () => {
    const records = [
      { key: 'pytest', durationMs: 1000, passed: true }
    ]
    // Median is 1000, multiplier is 3, so derived is 3000, but floor is 20000.
    const result = sizedTimeoutMs('pytest', {
      file: '/dev/null',
      read: mockRead(records),
      floorMs: 20000,
      capMs: 100000
    })
    expect(result).toBe(20000)
  })

  it('enforces the cap: never goes above capMs', () => {
    const records = [
      { key: 'pytest', durationMs: 100000, passed: true }
    ]
    // Median is 100000, multiplier is 3, so derived is 300000, but cap is 40000.
    const result = sizedTimeoutMs('pytest', {
      file: '/dev/null',
      read: mockRead(records),
      floorMs: 5000,
      capMs: 40000
    })
    expect(result).toBe(40000)
  })

  it('uses a custom multiplier', () => {
    const records = [
      { key: 'pytest', durationMs: 20000, passed: true }
    ]
    // Median is 20000, multiplier is 2, so timeout is 40000.
    const result = sizedTimeoutMs('pytest', {
      file: '/dev/null',
      read: mockRead(records),
      floorMs: 5000,
      capMs: 100000,
      multiplier: 2
    })
    expect(result).toBe(40000)
  })

  it('returns floorMs when no historical data is available', () => {
    const result = sizedTimeoutMs('pytest', {
      file: '/dev/null',
      read: () => [],
      floorMs: 20000,
      capMs: 100000
    })
    expect(result).toBe(20000)
  })

  it('exports DEFAULT_TEST_TIMEOUT_MS as the default floor and cap', () => {
    expect(DEFAULT_TEST_TIMEOUT_MS).toBe(1200_000)  // 20 minutes
  })
})

describe('countConcurrentPytest', () => {
  it('returns 0 when pgrep finds no matching processes (exit code 1)', () => {
    const exec = vi.fn(() => {
      const e = new Error('no matches')
      e.code = 1
      throw e
    })
    const result = countConcurrentPytest(exec)
    expect(result).toBe(0)
  })

  it('returns 0 when execSync reports exit status 1 (no matches)', () => {
    const exec = vi.fn(() => {
      const e = new Error('no matches')
      e.status = 1
      throw e
    })
    const result = countConcurrentPytest(exec)
    expect(result).toBe(0)
  })

  it('returns the count from pgrep -c output', () => {
    const exec = vi.fn().mockReturnValue({ stdout: '3\n' })
    const result = countConcurrentPytest(exec)
    expect(result).toBe(3)
    expect(exec).toHaveBeenCalledWith('pgrep', ['-c', '-f', 'pytest'], { stdio: 'pipe', shell: false })
  })

  it('returns null when pgrep is not available (ENOENT)', () => {
    const exec = vi.fn(() => {
      const e = new Error('pgrep not found')
      e.code = 'ENOENT'
      throw e
    })
    const result = countConcurrentPytest(exec)
    expect(result).toBeNull()
  })

  it('returns null for other exec failures', () => {
    const exec = vi.fn(() => {
      throw new Error('some other error')
    })
    const result = countConcurrentPytest(exec)
    expect(result).toBeNull()
  })

  it('returns null when stdout is not a valid number', () => {
    const exec = vi.fn().mockReturnValue({ stdout: 'not a number\n' })
    const result = countConcurrentPytest(exec)
    expect(result).toBeNull()
  })
})
