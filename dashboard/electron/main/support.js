import { execFile } from 'child_process'
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from 'fs'
import { homedir, tmpdir } from 'os'
import path from 'path'

// Support link between installs (ADR 0073): the IT button (helped install) and the Support tab (helper install).
// The work lives in lib/support.py (GitHub, labels, the helper's attempt, diagnostics); this reads its cache for an
// instant render and asks it for everything else. Twin of support.role() for the config.
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const SUPPORT_CLI = path.join(homedir(), '.agents', 'lib', 'support.py')
export const SUPPORT_DIR = path.join(homedir(), '.claude', 'support')
export const SUPPORT_STATE_PATH = path.join(SUPPORT_DIR, 'state.json')

const REPO = /^[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+$/
const STATES = ['trying-here', 'solved-here', 'helper-trying', 'needs-you', 'answered', 'verified',
  'idea-new', 'idea-proposal', 'idea-ticket', 'idea-shipped', 'idea-dismissed']

// { role: 'helped' | 'helper' | null, repos } from instance.json's "support" block; anything malformed is no support.
export function supportRole(config) {
  const s = config && typeof config === 'object' ? config.support : null
  if (!s || typeof s !== 'object' || Array.isArray(s)) return { role: null, repos: [] }
  const watch = Array.isArray(s.watch) ? s.watch.filter((r) => typeof r === 'string' && REPO.test(r)) : []
  if (watch.length) return { role: 'helper', repos: watch }
  if (typeof s.repo === 'string' && REPO.test(s.repo)) return { role: 'helped', repos: [s.repo] }
  return { role: null, repos: [] }
}

// The cache as the tabs need it, from disk only (no GitHub call): what renders the counter the moment the app opens.
export function readSupportState(file = SUPPORT_STATE_PATH) {
  try {
    const data = JSON.parse(readFileSync(file, 'utf8'))
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('not a cache')
    const requests = Array.isArray(data.requests) ? data.requests.filter((r) => r && typeof r === 'object' && STATES.includes(r.state)) : []
    const counts = Object.fromEntries(STATES.map((s) => [s, requests.filter((r) => r.open && r.state === s).length]))
    return { syncedAt: data.syncedAt || null, requests, counts, errors: data.errors && typeof data.errors === 'object' ? data.errors : {} }
  } catch {
    return { syncedAt: null, requests: [], counts: Object.fromEntries(STATES.map((s) => [s, 0])), errors: {} }
  }
}

// What the tab label shows: requests waiting on this person. Helper: needs-you. Helped: answered (a reply waiting).
export function badgeCount(role, state) {
  if (role === 'helper') return state.counts['needs-you'] || 0
  if (role === 'helped') return state.counts.answered || 0
  return 0
}

// Arguments for one support.py call, validated before anything runs. repos = this install's support repos.
export function supportArgs(cmd, { repo, number, file, check } = {}, repos = []) {
  const needsRequest = ['open', 'thread', 'resolve', 'draft', 'reply', 'followup', 'escalate', 'adapt']
  if (cmd === 'sync') return [SUPPORT_CLI, 'sync']
  if (cmd === 'file') return [SUPPORT_CLI, 'file', '--text-file', file]
  if (cmd === 'idea') return [SUPPORT_CLI, 'idea', '--text-file', file]
  if (!needsRequest.includes(cmd)) throw new Error(`not a support action: ${cmd}`)
  if (typeof repo !== 'string' || !repos.includes(repo)) throw new Error("that isn't one of this install's support repos")
  const n = Number(number)
  if (!Number.isInteger(n) || n <= 0) throw new Error(`"${number}" isn't a request number`)
  const args = [SUPPORT_CLI, cmd, repo, String(n)]
  if (cmd === 'reply' || cmd === 'followup' || cmd === 'adapt') args.push('--body-file', file)
  if (cmd === 'reply' && typeof check === 'string' && check.trim()) {
    if (check.length > 300) throw new Error('A check is one command, at most 300 characters')
    args.push('--check', check.trim())
  }
  return args
}

function call(args, run) {
  return new Promise((resolve) => {
    run(PY, args, { timeout: 330000 }, (err, stdout, stderr) => {
      try {
        resolve(JSON.parse(String(stdout).trim().split('\n').pop()))
      } catch {
        resolve({ ok: false, error: String(stderr || err?.message || 'support.py gave no answer').slice(0, 300) })
      }
    })
  })
}

// One action from the tab or the IT button. Text (a request, a reply) goes through a private temp file, never argv.
export async function runSupport(cmd, request = {}, { repos = [], run = execFile } = {}) {
  let dir = null
  try {
    let file
    if (cmd === 'file' || cmd === 'idea' || cmd === 'reply' || cmd === 'followup' || cmd === 'adapt') {
      const text = typeof request.text === 'string' ? request.text.trim() : ''
      if (!text) return { ok: false, error: cmd === 'file' ? "Say what's wrong first" : cmd === 'idea' ? 'Say what the idea is first' : 'The reply is empty' }
      dir = mkdtempSync(path.join(tmpdir(), 'marvin-support-'))
      file = path.join(dir, 'text.md')
      writeFileSync(file, text, { mode: 0o600 })
    }
    let args
    try {
      args = supportArgs(cmd, { ...request, file }, repos)
    } catch (err) {
      return { ok: false, error: err.message }
    }
    return await call(args, run)
  } finally {
    if (dir) rmSync(dir, { recursive: true, force: true })
  }
}

export function ensureSupportDir(dir = SUPPORT_DIR) {
  try {
    mkdirSync(dir, { recursive: true })
  } catch {}
}

// macOS notices from one saved state to the next (ADR 0073 amendment). The helped person hears when an answer arrives
// and when one of their ideas becomes a ticket or is built; the helper only when a request reaches needs-you. Only a change counts: a request already in that state before (or
// first seen at startup, when prev is null) never notifies, so reopening the app replays nothing.
export function supportNotices(prev, next, role) {
  if (!prev) return []
  const TITLES = role === 'helped'
    ? { answered: 'MARVIN support: a reply is waiting', 'idea-ticket': 'MARVIN: your idea is now a ticket', 'idea-shipped': 'MARVIN: your idea was built' }
    : role === 'helper' ? { 'needs-you': 'MARVIN support: a request needs you' } : {}
  const before = new Map((prev.requests || []).map((r) => [`${r.repo}#${r.number}`, r]))
  return (next.requests || [])
    .filter((r) => TITLES[r.state] && (r.open || r.state === 'idea-shipped'))
    .filter((r) => {
      const was = before.get(`${r.repo}#${r.number}`)
      return !was || was.state !== r.state || (!was.open && r.open)
    })
    .map((r) => ({ repo: r.repo, number: r.number, title: TITLES[r.state], body: String(r.title || '').slice(0, 120) }))
}
