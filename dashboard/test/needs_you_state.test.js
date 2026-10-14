import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readNeedsYouState, writeNeedsYouState } from '../electron/main/needs_you_state.js'

describe('needs_you_state', () => {
  const withDir = () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'needs-you-state-'))
    const filePath = path.join(dir, 'cache.json')
    return { filePath, done: () => rmSync(dir, { recursive: true, force: true }) }
  }

  // Test 1: reads valid cached state
  it('reads a valid cached state from disk', () => {
    const { filePath, done } = withDir()
    const state = { rows: [{ number: 1, title: 'T1' }], at: 1000 }
    writeFileSync(filePath, JSON.stringify(state))
    const read = readNeedsYouState(filePath)
    expect(read.rows).toEqual(state.rows)
    expect(read.at).toBe(state.at)
    expect(read.sort).toBe(null)
    done()
  })

  // Test 2: returns defaults for missing file
  it('returns defaults when the file does not exist', () => {
    const { filePath, done } = withDir()
    expect(readNeedsYouState(filePath)).toEqual({ rows: [], at: 0, sort: null })
    done()
  })

  // Test 3: returns defaults for invalid JSON
  it('returns defaults for invalid JSON', () => {
    const { filePath, done } = withDir()
    writeFileSync(filePath, 'not json')
    expect(readNeedsYouState(filePath)).toEqual({ rows: [], at: 0, sort: null })
    done()
  })

  // Test 4: returns defaults when rows is missing
  it('returns defaults when rows is missing', () => {
    const { filePath, done } = withDir()
    writeFileSync(filePath, JSON.stringify({ at: 1000 }))
    expect(readNeedsYouState(filePath)).toEqual({ rows: [], at: 1000, sort: null })
    done()
  })

  // Test 5: returns defaults when at timestamp is missing
  it('returns defaults when at timestamp is missing', () => {
    const { filePath, done } = withDir()
    writeFileSync(filePath, JSON.stringify({ rows: [] }))
    expect(readNeedsYouState(filePath)).toEqual({ rows: [], at: 0, sort: null })
    done()
  })

  // Test 6: returns defaults when rows is not an array
  it('returns defaults when rows is not an array', () => {
    const { filePath, done } = withDir()
    writeFileSync(filePath, JSON.stringify({ rows: {}, at: 1000 }))
    expect(readNeedsYouState(filePath)).toEqual({ rows: [], at: 1000, sort: null })
    done()
  })

  // Test 7: returns defaults when at is not a number
  it('returns defaults when at is not a number', () => {
    const { filePath, done } = withDir()
    writeFileSync(filePath, JSON.stringify({ rows: [], at: '1000' }))
    expect(readNeedsYouState(filePath)).toEqual({ rows: [], at: 0, sort: null })
    done()
  })

  // Test 8: writes state to disk and creates parent directories
  it('writes state to disk, creating parent directories if needed', () => {
    const { filePath, done } = withDir()
    const nested = path.join(filePath, '../nested/deep/state.json')
    const state = { rows: [{ number: 1, title: 'T1', repo: 'test/repo' }], at: 2000 }
    writeNeedsYouState(nested, state)
    const read = readNeedsYouState(nested)
    expect(read.rows).toEqual(state.rows)
    expect(read.at).toBe(state.at)
    done()
  })

  // Test 9: overwrites existing state file
  it('overwrites existing state when writing', () => {
    const { filePath, done } = withDir()
    const first = { rows: [{ number: 1 }], at: 1000 }
    const second = { rows: [{ number: 2 }], at: 2000 }
    writeNeedsYouState(filePath, first)
    const read1 = readNeedsYouState(filePath)
    expect(read1.rows).toEqual(first.rows)
    expect(read1.at).toBe(first.at)
    writeNeedsYouState(filePath, second)
    const read2 = readNeedsYouState(filePath)
    expect(read2.rows).toEqual(second.rows)
    expect(read2.at).toBe(second.at)
    done()
  })

  // Test 10: readNeedsYouState always returns { rows, at, sort } with defaults
  it('always returns fully-defaulted object with rows, at, sort', () => {
    const { filePath, done } = withDir()
    const read = readNeedsYouState(filePath)
    expect(read).toEqual({ rows: [], at: 0, sort: null })
    expect(read).toHaveProperty('rows')
    expect(read).toHaveProperty('at')
    expect(read).toHaveProperty('sort')
    done()
  })

  // Test 11: writeNeedsYouState merge-writes partial updates
  it('merge-writes partial state updates into existing state', () => {
    const { filePath, done } = withDir()
    writeNeedsYouState(filePath, { rows: [{ number: 1 }], at: 1000 })
    writeNeedsYouState(filePath, { sort: 'priority' })
    const read = readNeedsYouState(filePath)
    expect(read.rows).toHaveLength(1)
    expect(read.at).toBe(1000)
    expect(read.sort).toBe('priority')
    done()
  })

  // Test 12: writeNeedsYouState never throws on errors
  it('never throws even if mkdir or write fails', () => {
    const bad = '/dev/null/impossible/path/to/file.json'
    expect(() => {
      writeNeedsYouState(bad, { rows: [], at: 1000 })
    }).not.toThrow()
  })
})
