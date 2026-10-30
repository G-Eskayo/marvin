import { readFileSync, writeFileSync, renameSync, mkdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// marvin#762: every Approve click, written down BEFORE it is sent: { url, number, head, clickedAt, outcome, machine,
// reason, attempts, updatedAt }. On 2026-10-29 seven clicks failed and nothing recorded which PRs they were for.
//
// outcome: sending (written, not yet answered) | merged | reengaged | refused | interrupted | queued (no machine could
// take it) | waiting-memory (marvin#940: `machine` refused it for memory and queued it to run by itself) |
// merged-elsewhere | closed. Waiting for a retry: `queued`, `waiting-memory`, and `interrupted` (the webhook went away
// mid-merge; owner decision on #766) when the Mac it was on is known and it has been sent fewer than 3 times. Every
// other outcome is a machine's answer. An interrupted one is only ever retried on that same Mac (approve_flow.js).
//
// Per machine, in ~/.claude/logs (not synced): a click is retried from the dashboard where it was made, so two Macs
// never both retry it. The Health check (lib/health_checks.py, merge:service) reads the same file for its count.
// One small JSON file, rewritten whole through a temp file and a rename, so a crash mid-write leaves the old one.
export const APPROVALS_PATH = path.join(homedir(), '.claude', 'logs', 'approvals.json')
// A PR whose merge keeps killing its webhook is not re-run on every wake and unlock: 3 sends, then Approve by hand.
export const INTERRUPTED_RETRIES = 3
const isWaiting = (a) => a.outcome === 'queued' || a.outcome === 'waiting-memory' || (a.outcome === 'interrupted' && !!a.machine && (a.attempts || 0) < INTERRUPTED_RETRIES)

export function createApprovalLedger(file = APPROVALS_PATH, { now = Date.now, cap = 200 } = {}) {
  const read = () => {
    try {
      const list = JSON.parse(readFileSync(file, 'utf8'))?.approvals
      return Array.isArray(list) ? list.filter((a) => a && typeof a.url === 'string') : []
    } catch {
      return []
    }
  }
  // Bounded: the newest `cap` answered entries are kept; a waiting one is never dropped. O(n log n) per write, n <= cap.
  const write = (list) => {
    const waiting = list.filter(isWaiting)
    const done = list.filter((a) => !isWaiting(a)).sort((a, b) => b.updatedAt - a.updatedAt).slice(0, cap)
    const out = [...waiting, ...done].sort((a, b) => a.clickedAt - b.clickedAt)
    mkdirSync(path.dirname(file), { recursive: true })
    const tmp = `${file}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify({ approvals: out }, null, 1))
    renameSync(tmp, file)
  }
  const update = (url, fn) => {
    const list = read()
    const i = list.findIndex((a) => a.url === url)
    const next = fn(i >= 0 ? list[i] : null)
    if (i >= 0) list.splice(i, 1)
    if (next) list.push(next)
    write(list)
    return next
  }
  return {
    // A click (or a retry of one): the original click time is kept, so "oldest first" means the order they were made.
    record(url, { number = null, head = null } = {}) {
      const t = now()
      return update(url, (prev) => ({
        url, number: number ?? prev?.number ?? null, head: head ?? prev?.head ?? null,
        clickedAt: prev && isWaiting(prev) ? prev.clickedAt : t,
        outcome: 'sending', machine: null, reason: null, attempts: (prev && isWaiting(prev) ? prev.attempts || 1 : 0) + 1, updatedAt: t
      }))
    },
    // unsent: this try never reached a machine that took it (unreachable, or already merging it), so it is not counted.
    conclude(url, outcome, { machine = null, reason = null, unsent = false } = {}) {
      return update(url, (prev) => prev && {
        ...prev, outcome, machine, reason: reason == null ? null : String(reason).slice(0, 500),
        attempts: unsent ? Math.max(0, (prev.attempts || 1) - 1) : prev.attempts, updatedAt: now()
      })
    },
    drop(url) { update(url, () => null) },
    get: (url) => read().find((a) => a.url === url) || null,
    waiting: () => read().filter(isWaiting).sort((a, b) => a.clickedAt - b.clickedAt)
  }
}
