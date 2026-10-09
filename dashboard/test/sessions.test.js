import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readLiveSessions } from '../webhook-server/sessions.js'
import { writeFileSync, mkdirSync, rmSync } from 'fs'
import path from 'path'
import os from 'os'

describe('readLiveSessions: live sessions from session_work.py', () => {
  let tmpDir
  beforeEach(() => {
    tmpDir = path.join(os.tmpdir(), `sessions-test-${Date.now()}`)
    mkdirSync(tmpDir, { recursive: true })
  })

  afterEach(() => {
    try {
      rmSync(tmpDir, { recursive: true })
    } catch (e) {
      // ignore
    }
  })

  it('returns empty object for missing file', () => {
    expect(readLiveSessions(path.join(tmpDir, 'nonexistent.json'))).toEqual({})
  })

  it('returns empty object for corrupt/non-JSON file', () => {
    const file = path.join(tmpDir, 'corrupt.json')
    writeFileSync(file, 'not json')
    expect(readLiveSessions(file)).toEqual({})
  })

  it('returns exact sessions object for valid file', () => {
    const fixture = {
      sessions: {
        A: { request: 'fix health', last: 1000, files: { 'r|lib/h.py': 1000 }, claimed: [] },
        B: { request: 'add feature', last: 1001, files: { 'r|lib/f.py': 1001 }, claimed: [] }
      }
    }
    const file = path.join(tmpDir, 'sessions-fixture.json')
    writeFileSync(file, JSON.stringify(fixture))
    const result = readLiveSessions(file)
    expect(result).toEqual(fixture.sessions)
  })

  it('returns empty object for valid JSON without sessions key', () => {
    const file = path.join(tmpDir, 'no-sessions.json')
    writeFileSync(file, JSON.stringify({ other: 'data' }))
    expect(readLiveSessions(file)).toEqual({})
  })

  it('returns empty object when sessions is not a dict', () => {
    const file = path.join(tmpDir, 'bad-sessions.json')
    writeFileSync(file, JSON.stringify({ sessions: 'not a dict' }))
    expect(readLiveSessions(file)).toEqual({})
  })
})
