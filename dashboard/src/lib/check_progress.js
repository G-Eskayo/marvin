// The numbers behind a PR card's checks progress (marvin#555, approved by Gil 2026-10-21):
//   [██████████░░░░░]  2 of 3 done
//   Still running: App builds (iOS) · 4:05
//   Last checked 20 s ago
// Pure: everything is computed from the check rows and a clock passed in, so the times tick in the UI without asking
// GitHub again. Times GitHub didn't give are left blank, never guessed; clock skew shows 0, never a negative time.

// Epoch ms or an ISO string -> ms; anything unusable (including 0) -> null.
export function toMs(v) {
  if (typeof v === 'number') return Number.isFinite(v) && v > 0 ? v : null
  if (typeof v !== 'string' || !v) return null
  const t = Date.parse(v)
  return Number.isFinite(t) && t > 0 ? t : null
}

// 48 s -> "0:48", 245 s -> "4:05", 3723 s -> "1:02:03". Unknown -> "".
export function formatClock(ms) {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return ''
  const total = Math.floor(Math.max(0, ms) / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

// How long ago, in the unit that reads naturally: "20 s ago", "4 min ago", "3 h ago". Unknown -> null.
export function formatAgo(ms) {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return null
  const s = Math.floor(Math.max(0, ms) / 1000)
  if (s < 60) return `${s} s ago`
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  return `${Math.floor(s / 3600)} h ago`
}

const span = (from, to) => (from == null || to == null ? null : Math.max(0, to - from))

// rows: one per check, in GitHub's order. time: how long it took (finished) or how long so far (not finished), or null.
// running: the checks not finished yet (running or queued), for the "Still running" line.
export function summarizeChecks(runs, now) {
  const rows = (Array.isArray(runs) ? runs : [])
    .filter((r) => r && typeof r === 'object')
    .map((r) => {
      const started = toMs(r.startedAt)
      const time = r.done ? span(started, toMs(r.completedAt)) : span(started, now)
      return { name: String(r.name ?? 'check'), status: r.status, label: String(r.status ?? ''), done: !!r.done, time }
    })
  const total = rows.length
  const done = rows.filter((r) => r.done).length
  return {
    total,
    done,
    percent: total ? Math.round((done / total) * 100) : 0,
    running: rows.filter((r) => !r.done).map(({ name, status, time }) => ({ name, status, time })),
    rows: rows.map(({ name, status, label, time }) => ({ name, status, label, time }))
  }
}

// "App builds (iOS) · 4:05", several joined with commas, more than `max` cut to "and N more".
export function runningLine(summary, max = 2) {
  const list = summary?.running || []
  const shown = list.slice(0, max).map((r) => (r.time == null ? r.name : `${r.name} · ${formatClock(r.time)}`)).join(', ')
  return list.length > max ? `${shown} and ${list.length - max} more` : shown
}
