import { NOTE_CAP, validNote } from '../../src/lib/safety_reviews.js'

// Health ▸ Safety reviews (approved 2026-10-26): the safety monitor's quarantine, one entry at a time. The file, its
// parser and its one writer all live in skills/safety-monitor/scripts/process_quarantine_reviews.py (`list`, `answer`);
// this side only runs it (execFile: argv items, never a shell) and checks what comes back. Entry text is model output:
// it stays plain strings here and is rendered as text. Read on open and when ~/.claude/quarantine.md changes (the
// 'quarantine' file trigger), never on a timer. O(file) per read.

const ID = /^[0-9a-f]{16}$/
const KINDS = new Set(['approve', 'modify', 'deny'])
const str = (v) => (typeof v === 'string' ? v : '')
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

export function cleanList(raw) {
  const entries = (Array.isArray(raw?.entries) ? raw.entries : [])
    .filter((e) => e && typeof e === 'object' && ID.test(str(e.id)))
    .map((e) => ({
      id: e.id, date: str(e.date), loop: str(e.loop), score: num(e.score), tau: num(e.tau),
      reason: str(e.reason), excerpt: str(e.excerpt), body: str(e.body), truncated: e.truncated === true
    }))
  const unreadable = Number.isInteger(raw?.unreadable) ? raw.unreadable : 0
  return { entries, pending: entries.length, unreadable }
}

const parse = (stdout) => {
  const out = JSON.parse(String(stdout).trim().split('\n').pop())
  if (!out || typeof out !== 'object') throw new Error('no result')
  return out
}

// run(args) -> the script's stdout (index.js: the venv python on the script).
export function createSafetyReviews({ run }) {
  return {
    async list() {
      try {
        return cleanList(parse(await run(['list'])))
      } catch (err) {
        return { entries: [], pending: 0, unreadable: 0, error: `Could not read the safety reviews: ${err?.message || err}` }
      }
    },
    async answer(id, kind, text) {
      if (typeof id !== 'string' || !ID.test(id) || !KINDS.has(kind)) return { status: 'invalid', reason: 'request' }
      const args = ['answer', '--id', id, '--kind', kind]
      if (kind === 'modify') {
        const note = typeof text === 'string' ? text : ''
        if (!note.trim()) return { status: 'invalid', reason: 'empty' }
        if (!validNote(note)) return { status: 'invalid', reason: 'too-long' }
        args.push('--text', note)
      }
      try {
        const out = parse(await run(args))
        return typeof out.status === 'string' ? out : { status: 'failed', error: 'no status' }
      } catch (err) {
        return { status: 'failed', error: String(err?.message || err) }
      }
    }
  }
}

export { NOTE_CAP }
