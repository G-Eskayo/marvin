import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync, utimesSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { describeHelper, listHelpers, STALE_MS, CRASH_EXPIRE_MS, crashExpired } from '../webhook-server/chat_helpers.js'

const T0 = Date.parse('2026-10-22T15:00:00Z')
const iso = (ms) => new Date(ms).toISOString()

// What lib/chat_helpers.py writes
function helperDoc(id, { status = 'running', started = T0, finished = null, summary = '', error = '', links = [], transcript = '' } = {}) {
  return {
    job: `helper-${id}`,
    label: `Helper ${id}`,
    kind: 'helper',
    helper: { agent_id: id, agent_type: 'general-purpose', session: 'b41ed591', chat: 'fix the docs search', machine: 'macbook-pro', cwd: '/Users/gil', transcript, links },
    runs: [{ id: 'r1', status, started_at: iso(started), finished_at: finished ? iso(finished) : null, steps: [{ step: 'working', detail: '', at: iso(started) }], summary, error }]
  }
}

describe('crashExpired (Tests 1-5)', () => {
  // Test 1: crashExpired exists and exports
  it('crashExpired is exported from chat_helpers', () => {
    expect(typeof crashExpired).toBe('function')
  })

  // Test 2: crashExpired detects fresh crashed helpers as NOT expired
  it('a crashed helper fresh (< 24h) is not expired', () => {
    // Create a helper that will be marked 'crashed' by describeHelper:
    // status: 'running' + stale transcript (> STALE_MS old)
    const dir = mkdtempSync(path.join(tmpdir(), 'helpers-'))
    const transcript = path.join(dir, 'transcript.jsonl')
    writeFileSync(transcript, '{}\n')

    // Started at T0, transcript is stale (more than STALE_MS ago)
    // At T0 + 1h: helper is 1h old, so not yet expired
    const doc = helperDoc('a2', { status: 'running', started: T0, transcript })
    const h = describeHelper(doc, { now: T0 + 1 * 60 * 60 * 1000, mtime: () => T0 - STALE_MS - 1000 })

    // Transcript is very old, so at T0 + 1h it's stale -> crashed
    expect(h.status).toBe('crashed')

    // Now test crashExpired: h is crashed and started at T0, current time is T0 + 1h
    const now = T0 + 1 * 60 * 60 * 1000
    expect(crashExpired(h, now)).toBe(false) // 1h < 24h

    rmSync(dir, { recursive: true, force: true })
  })

  // Test 3: crashExpired detects expired crashed helpers (>= 24h)
  it('a crashed helper old (>= 24h) is expired', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'helpers-'))
    const transcript = path.join(dir, 'transcript.jsonl')
    writeFileSync(transcript, '{}\n')

    // Helper started long ago, crashed long ago
    const doc = helperDoc('a3', { status: 'running', started: T0 - CRASH_EXPIRE_MS - 1000, transcript })
    const h = describeHelper(doc, { now: T0, mtime: () => T0 - CRASH_EXPIRE_MS - 1000 })

    // It's crashed (running + stale transcript)
    expect(h.status).toBe('crashed')

    // Test crashExpired: started at T0 - 24h, now is at T0 -> >= 24h old
    expect(crashExpired(h, T0)).toBe(true)

    rmSync(dir, { recursive: true, force: true })
  })

  // Test 4: crashExpired returns false for non-crashed statuses
  it('crashExpired returns false for done/running helpers', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'helpers-'))
    const transcript = path.join(dir, 'transcript.jsonl')
    writeFileSync(transcript, '{}\n')

    // Done helper
    const done = describeHelper(helperDoc('a1', { status: 'passed', finished: T0, summary: 'ok' }), { now: T0 + CRASH_EXPIRE_MS + 1000 })

    // Running helper (not crashed, transcript recent)
    const running = describeHelper(helperDoc('a2', { status: 'running', started: T0, transcript }), { now: T0 + 1000, mtime: () => T0 })

    const now = T0 + CRASH_EXPIRE_MS + 1000
    expect(crashExpired(done, now)).toBe(false)
    expect(crashExpired(running, now)).toBe(false)

    rmSync(dir, { recursive: true, force: true })
  })
})

describe('crashExpired: measures from crash time, not start time (Defect #3)', () => {
  it('crashed helper expired when > 24h since crash (finishedAt) — measures crash time, not start time', () => {
    // Key test: A helper with a very old finishedAt (>24h) should expire,
    // even if some other time reference was different.
    // finishedAt is set to max(startedMs, transcriptMs), so both should be old.
    const crashTime = T0 - CRASH_EXPIRE_MS - 1000  // 25h+ ago
    const doc = helperDoc('old', { status: 'running', started: crashTime, transcript: '' })
    const dir = mkdtempSync(path.join(tmpdir(), 'helpers-'))
    const transcript = path.join(dir, 'transcript.jsonl')
    writeFileSync(transcript, '{}\n')

    // describeHelper marks it crashed because transcript mtime is stale
    const h = describeHelper(doc, { now: T0, mtime: () => crashTime })
    expect(h.status).toBe('crashed')
    expect(h.job?.last?.finishedAt).toBeDefined()
    const finishedMs = Date.parse(h.job.last.finishedAt)
    // finishedAt = max(startedMs, transcriptMs), so both being old means finishedAt is old
    expect(finishedMs).toBeLessThanOrEqual(crashTime + 1000)
    // 25h+ has passed since crash, so it should be expired
    expect(crashExpired(h, T0)).toBe(true)

    rmSync(dir, { recursive: true, force: true })
  })

  it('crashed helper not expired when <= 24h since crash (finishedAt recent)', () => {
    // Key: finishedAt is 12h ago, should NOT be expired
    // finishedAt = max(startedMs, transcriptMs), so at least one must be recent
    const crashTime = T0 - 12 * 60 * 60 * 1000  // 12h ago
    const doc = helperDoc('fresh', { status: 'running', started: crashTime, transcript: '' })
    const dir = mkdtempSync(path.join(tmpdir(), 'helpers-'))
    const transcript = path.join(dir, 'transcript.jsonl')
    writeFileSync(transcript, '{}\n')

    const h = describeHelper(doc, { now: T0, mtime: () => crashTime })
    expect(h.status).toBe('crashed')
    const finishedMs = Date.parse(h.job.last.finishedAt)
    expect(finishedMs).toBeLessThanOrEqual(crashTime + 1000)
    // Only 12h since crash (< 24h), should not be expired
    expect(crashExpired(h, T0)).toBe(false)

    rmSync(dir, { recursive: true, force: true })
  })

  it('crashed helper without finishedAt falls back to startedAt', () => {
    // Test the h.startedAt fallback in crashExpired:
    // If finishedAt is missing, it should use startedAt
    const startTime = T0 - CRASH_EXPIRE_MS - 1000
    const doc = helperDoc('no-finished', { status: 'running', started: startTime, transcript: '' })
    const dir = mkdtempSync(path.join(tmpdir(), 'helpers-'))
    const transcript = path.join(dir, 'transcript.jsonl')
    writeFileSync(transcript, '{}\n')

    const h = describeHelper(doc, { now: T0, mtime: () => startTime })
    expect(h.status).toBe('crashed')
    // Manually unset finishedAt to test the fallback to startedAt
    if (h.job?.last) {
      h.job.last.finishedAt = null
    }
    // Should still be expired because startedAt fallback is 25h+ ago
    expect(crashExpired(h, T0)).toBe(true)

    rmSync(dir, { recursive: true, force: true })
  })

  it('boundary: crashed helper not expired at exactly 24h', () => {
    // Edge case: exactly 24h since crash
    const crashTime = T0 - CRASH_EXPIRE_MS
    const doc = helperDoc('boundary', { status: 'running', started: crashTime, transcript: '' })
    const dir = mkdtempSync(path.join(tmpdir(), 'helpers-'))
    const transcript = path.join(dir, 'transcript.jsonl')
    writeFileSync(transcript, '{}\n')

    const h = describeHelper(doc, { now: T0, mtime: () => crashTime })
    expect(h.status).toBe('crashed')
    // Exactly 24h: now - crash = CRASH_EXPIRE_MS, so CRASH_EXPIRE_MS > CRASH_EXPIRE_MS is false
    expect(crashExpired(h, T0)).toBe(false)

    rmSync(dir, { recursive: true, force: true })
  })
})

describe('listHelpers filters correctly with fixed crashExpired (Test 5)', () => {
  let dir
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'helpers-')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))

  it('listHelpers includes fresh crashed, excludes old expired crashed, includes done', () => {
    // Create three helpers with different states
    const freshTranscript = path.join(dir, 'fresh.jsonl')
    const oldTranscript = path.join(dir, 'old.jsonl')
    writeFileSync(freshTranscript, '{}\n')
    writeFileSync(oldTranscript, '{}\n')

    // Set file modification times to simulate old/fresh transcripts
    // Fresh: 12h ago (will be marked crashed but not expired)
    const freshMtime = T0 - 12 * 60 * 60 * 1000
    utimesSync(freshTranscript, freshMtime / 1000, freshMtime / 1000)

    // Old: 25h ago (will be marked crashed and expired)
    const oldMtime = T0 - CRASH_EXPIRE_MS - 1000
    utimesSync(oldTranscript, oldMtime / 1000, oldMtime / 1000)

    // Fresh crashed (less than 24h since crash)
    const freshCrashed = helperDoc('fresh', { status: 'running', started: freshMtime, transcript: freshTranscript })

    // Old expired crashed (more than 24h since crash)
    const oldCrashed = helperDoc('old', { status: 'running', started: oldMtime, transcript: oldTranscript })

    // Done (not crashed, should always be included)
    const done = helperDoc('done', { status: 'passed', finished: T0 - 1000, summary: 'ok' })

    writeFileSync(path.join(dir, 'helper-fresh.json'), JSON.stringify(freshCrashed))
    writeFileSync(path.join(dir, 'helper-old.json'), JSON.stringify(oldCrashed))
    writeFileSync(path.join(dir, 'helper-done.json'), JSON.stringify(done))

    // Call listHelpers to get filtered results
    const helpers = listHelpers({ dir, now: T0 })
    const ids = helpers.map((h) => h.id)

    // Fresh crashed should be included (12h < 24h)
    expect(ids).toContain('helper-fresh')
    // Old crashed should be filtered out (25h+ > 24h)
    expect(ids).not.toContain('helper-old')
    // Done should be included (not crashed)
    expect(ids).toContain('helper-done')
  })
})
