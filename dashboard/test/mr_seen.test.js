import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { readSeenNumbers, markSeen, computeReviewStatus } from '../electron/main/mr_seen.js'

function withTempDir(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'mr-seen-test-'))
  try {
    return fn(join(dir, 'mr-seen.json'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('readSeenNumbers', () => {
  it('returns an empty array when the file does not exist', () => {
    withTempDir((path) => {
      expect(readSeenNumbers(path)).toEqual([])
    })
  })

  it('returns an empty array when the file is corrupt', () => {
    withTempDir((path) => {
      writeFileSync(path, 'not json')
      expect(readSeenNumbers(path)).toEqual([])
    })
  })
})

describe('markSeen', () => {
  it('persists PR numbers so a later read sees them', () => {
    withTempDir((path) => {
      markSeen(path, [1, 2, 3])
      expect(readSeenNumbers(path)).toEqual([1, 2, 3])
    })
  })

  it('accumulates across calls instead of overwriting', () => {
    withTempDir((path) => {
      markSeen(path, [1, 2])
      markSeen(path, [3])
      expect(new Set(readSeenNumbers(path))).toEqual(new Set([1, 2, 3]))
    })
  })

  it('does not duplicate a number marked seen twice', () => {
    withTempDir((path) => {
      markSeen(path, [1])
      markSeen(path, [1])
      expect(readSeenNumbers(path)).toEqual([1])
    })
  })

  it('creates parent directories that do not exist yet', () => {
    withTempDir((path) => {
      const nested = join(path, '..', 'nested', 'mr-seen.json')
      markSeen(nested, [5])
      expect(readSeenNumbers(nested)).toEqual([5])
    })
  })
})

describe('computeReviewStatus', () => {
  it('is green when there are no open PRs', () => {
    expect(computeReviewStatus([], [1, 2, 3])).toBe('green')
  })

  it('is red when at least one open PR has never been seen', () => {
    expect(computeReviewStatus([1, 2], [1])).toBe('red')
  })

  it('is blue when every open PR has already been seen', () => {
    expect(computeReviewStatus([1, 2], [1, 2, 3])).toBe('blue')
  })

  it('is red when nothing has ever been seen', () => {
    expect(computeReviewStatus([1], [])).toBe('red')
  })
})
