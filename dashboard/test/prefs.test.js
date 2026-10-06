import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readPrefs, DEFAULT_PREFS } from '../electron/main/prefs.js'

describe('readPrefs', () => {
  const withFile = (text) => {
    const dir = mkdtempSync(path.join(tmpdir(), 'prefs-'))
    const file = path.join(dir, 'prefs.json')
    if (text !== null) writeFileSync(file, text)
    return { file, done: () => rmSync(dir, { recursive: true, force: true }) }
  }

  it('merging asks for no extra confirmation by default: the Approve & Merge click is the decision', () => {
    expect(DEFAULT_PREFS.confirmMerge).toBe(false)
  })
  it('a missing or unreadable file gives the defaults', () => {
    const a = withFile(null); const b = withFile('{not json')
    expect(readPrefs(a.file)).toEqual(DEFAULT_PREFS)
    expect(readPrefs(b.file)).toEqual(DEFAULT_PREFS)
    a.done(); b.done()
  })
  it('turns confirmation back on when asked, and ignores unknown or wrongly-typed values', () => {
    const f = withFile('{"confirmMerge": true, "surprise": 1}')
    expect(readPrefs(f.file)).toEqual({ ...DEFAULT_PREFS, confirmMerge: true })
    f.done()
    const g = withFile('{"confirmMerge": "yes"}')
    expect(readPrefs(g.file).confirmMerge).toBe(false)
    g.done()
  })
})
