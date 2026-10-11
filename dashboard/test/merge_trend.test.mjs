/**
 * Tests for merge_trend.js: thin wrapper around merge_trend.py recording.
 * Written to break it: python not found, merge_trend.py missing, bad PR URL, fire-and-forget behavior, and unref() issues.
 *
 * npm run test -- dashboard/test/merge_trend.test.mjs
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { recordMergeTrend } from '../webhook-server/merge_trend.js'

describe('merge_trend.js', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('should call venv Python with merge_trend.py, repo, and PR URL', () => {
    const mockChild = {
      on: vi.fn(),
      unref: vi.fn().mockReturnValue(undefined)
    }
    const spawnFn = vi.fn().mockReturnValue(mockChild)

    recordMergeTrend('https://github.com/G-Eskayo/marvin/pull/123', 'G-Eskayo/marvin', spawnFn)

    expect(spawnFn).toHaveBeenCalled()
    const [cmd, args, opts] = spawnFn.mock.calls[0]
    expect(cmd).toContain('venv/bin/python')
    expect(args[0]).toContain('lib/merge_trend.py')
    expect(args[1]).toBe('G-Eskayo/marvin')
    expect(args[2]).toBe('https://github.com/G-Eskayo/marvin/pull/123')
  })

  it('should be fire-and-forget (not throw on spawn error)', () => {
    const spawnFn = vi.fn().mockImplementation(() => {
      throw new Error('python not found')
    })

    // Should not throw even if spawn fails
    expect(() => recordMergeTrend('https://github.com/G-Eskayo/marvin/pull/200', 'G-Eskayo/marvin', spawnFn)).not.toThrow()
  })

  it('should extract repo from PR URL if not provided', () => {
    const mockChild = {
      on: vi.fn(),
      unref: vi.fn().mockReturnValue(undefined)
    }
    const spawnFn = vi.fn().mockReturnValue(mockChild)

    recordMergeTrend('https://github.com/G-Eskayo/marvin/pull/50', undefined, spawnFn)

    expect(spawnFn).toHaveBeenCalled()
    const [cmd, args] = spawnFn.mock.calls[0]
    expect(args).toContain('G-Eskayo/marvin')
  })

  it('should handle missing repo gracefully (skip if malformed URL)', () => {
    const spawnFn = vi.fn()

    recordMergeTrend('not-a-valid-url', undefined, spawnFn)

    // Should not call spawn for invalid URL
    expect(spawnFn).not.toHaveBeenCalled()
  })

  it('should use detached process with stdio ignored', () => {
    const mockChild = {
      on: vi.fn(),
      unref: vi.fn().mockReturnValue(undefined)
    }
    const spawnFn = vi.fn().mockReturnValue(mockChild)

    recordMergeTrend('https://github.com/G-Eskayo/marvin/pull/99', 'G-Eskayo/marvin', spawnFn)

    const [cmd, args, opts] = spawnFn.mock.calls[0]
    expect(opts.detached).toBe(true)
    expect(opts.stdio).toBe('ignore')
  })

  it('should call unref() on the spawned child to detach it', () => {
    const mockChild = {
      on: vi.fn(),
      unref: vi.fn().mockReturnValue(undefined)
    }
    const spawnFn = vi.fn().mockReturnValue(mockChild)

    recordMergeTrend('https://github.com/G-Eskayo/marvin/pull/88', 'G-Eskayo/marvin', spawnFn)

    expect(mockChild.unref).toHaveBeenCalled()
  })

  it('should attach error handler to prevent crashes on spawn errors', () => {
    const mockChild = {
      on: vi.fn(),
      unref: vi.fn().mockReturnValue(undefined)
    }
    const spawnFn = vi.fn().mockReturnValue(mockChild)

    recordMergeTrend('https://github.com/G-Eskayo/marvin/pull/77', 'G-Eskayo/marvin', spawnFn)

    expect(mockChild.on).toHaveBeenCalledWith('error', expect.any(Function))
  })

  it('should return immediately (synchronous fire-and-forget)', () => {
    const mockChild = {
      on: vi.fn(),
      unref: vi.fn().mockReturnValue(undefined)
    }
    const spawnFn = vi.fn().mockReturnValue(mockChild)

    const start = performance.now()
    recordMergeTrend('https://github.com/G-Eskayo/marvin/pull/66', 'G-Eskayo/marvin', spawnFn)
    const elapsed = performance.now() - start

    // Should return almost immediately (no waiting for process)
    expect(elapsed).toBeLessThan(100)
  })
})
