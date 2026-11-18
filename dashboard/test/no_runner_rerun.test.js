import { describe, it, expect } from 'vitest'
import { readNoRunnerReruns, recordNoRunnerRerun, noRunnerKey } from '../webhook-server/no_runner_rerun.js'
import { mkdtempSync, writeFileSync, unlinkSync } from 'fs'
import { join } from 'path'
import { tmpdir } from 'os'

describe('noRunnerKey', () => {
  it('creates a key from repo, number, headSha, and runId', () => {
    const key = noRunnerKey('owner/repo', 123, 'abc123', '456')
    expect(key).toMatch(/owner\/repo#123@abc123@456/)
  })

  it('includes all four parts to prevent collisions', () => {
    const key1 = noRunnerKey('a/b', 1, 'sha1', '1')
    const key2 = noRunnerKey('a/b', 1, 'sha2', '1')
    const key3 = noRunnerKey('a/b', 2, 'sha1', '1')
    const key4 = noRunnerKey('a/b', 1, 'sha1', '2')
    expect(new Set([key1, key2, key3, key4]).size).toBe(4)
  })

  it('handles different repos correctly', () => {
    const key1 = noRunnerKey('a/b', 1, 'sha', 'run')
    const key2 = noRunnerKey('c/d', 1, 'sha', 'run')
    expect(key1).not.toBe(key2)
  })
})

describe('readNoRunnerReruns / recordNoRunnerRerun (read-write round trip)', () => {
  const tempDir = mkdtempSync(join(tmpdir(), 'no-runner-'))
  const testFile = join(tempDir, 'no-runner-reruns.json')

  it('write then read returns the same entry under its exact key', () => {
    const key = noRunnerKey('owner/repo', 123, 'abc', '456')
    const entry = { result: 'reran', at: new Date().toISOString() }
    recordNoRunnerRerun(key, entry, testFile, () => new Date())
    const read = readNoRunnerReruns(testFile)
    expect(read[key]).toEqual(entry)
  })

  it('two different keys never collide, including two different repos with the same headSha', () => {
    const file = join(tempDir, 'collision-test.json')
    const key1 = noRunnerKey('a/b', 1, 'same-sha', '1')
    const key2 = noRunnerKey('c/d', 1, 'same-sha', '1')
    recordNoRunnerRerun(key1, { result: 'reran', at: new Date().toISOString() }, file, () => new Date())
    recordNoRunnerRerun(key2, { result: 'reran', at: new Date().toISOString() }, file, () => new Date())
    const read = readNoRunnerReruns(file)
    expect(read[key1]).toBeDefined()
    expect(read[key2]).toBeDefined()
    expect(read[key1]).not.toBe(read[key2])
  })

  it('entries older than the TTL (7 days) are dropped on the next write', () => {
    const file = join(tempDir, 'ttl-test.json')
    const now = new Date('2026-11-17')
    const eightDaysAgo = new Date('2026-11-09')
    const key = noRunnerKey('owner/repo', 1, 'sha', 'run')

    recordNoRunnerRerun(key, { result: 'reran', at: eightDaysAgo.toISOString() }, file, () => now)
    recordNoRunnerRerun(key, { result: 'reran', at: now.toISOString() }, file, () => now)

    const read = readNoRunnerReruns(file)
    expect(Object.keys(read).length).toBe(1)
    expect(read[key].at).toBe(now.toISOString())
  })

  it('reading a missing file returns {}', () => {
    const result = readNoRunnerReruns(join(tempDir, 'nonexistent.json'))
    expect(result).toEqual({})
  })

  it('reading a corrupt file returns {}, never throws', () => {
    const file = join(tempDir, 'corrupt.json')
    writeFileSync(file, 'not json')
    const result = readNoRunnerReruns(file)
    expect(result).toEqual({})
  })
})
