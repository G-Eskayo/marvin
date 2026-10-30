// A merge's progress, stage by stage (marvin#568). The webhook's merge gate emits one event per stage change (about 8
// per merge, plus a bounded number of test-count updates); the same reducer folds them in the webhook, in the main
// process (what a card reads when it mounts) and so in the card. Pure: no clock, no I/O.
//
// Event: { id, seq, stage, state, at, detail?, count?: {done, total, unit}, machine?, estimateMs? }
//   id    one merge attempt (events from another attempt are ignored)
//   seq   increases per event within an attempt; a duplicate or late event (seq <= the last applied) is ignored
//   state running | done | failed | skipped
// The pipeline is sequential, so a stage starting closes every earlier one: a running one as done, a waiting one as
// skipped. That keeps the picture right when an event is lost or arrives out of order.

export const MERGE_STAGES = [
  ['queued', 'Queued'],
  ['fetching', 'Fetching PR'],
  ['rebasing', 'Rebasing on main'],
  ['installing', 'Installing'],
  ['tests', 'Tests'],
  ['merging', 'Merging on GitHub'],
  ['after', 'After-merge checks'],
  ['done', 'Done']
]
const ORDER = new Map(MERGE_STAGES.map(([k], i) => [k, i]))
const STATES = new Set(['running', 'done', 'failed', 'skipped'])
const FINAL = new Set(['done', 'failed', 'skipped'])
const MAX_DETAIL = 300

export function emptyProgress() {
  return { id: null, seq: 0, stages: {}, machine: null, estimateMs: null, outcome: null }
}

const cut = (s) => (typeof s === 'string' ? s.slice(0, MAX_DETAIL) : undefined)
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

function cleanCount(c) {
  if (!c || typeof c !== 'object') return undefined
  const done = num(c.done), total = num(c.total)
  if (done == null || total == null || done < 0 || total <= 0) return undefined
  return { done: Math.min(done, total), total, unit: c.unit === '%' ? '%' : 'files' }
}

export function applyMergeEvent(progress, event) {
  const p = progress && typeof progress === 'object' ? progress : emptyProgress()
  if (!event || typeof event !== 'object') return p
  const { stage, state } = event
  const seq = num(event.seq)
  if (seq == null || !ORDER.has(stage) || !STATES.has(state)) return p
  if (p.id && event.id && event.id !== p.id) return p
  if (seq <= p.seq || p.outcome) return p
  const cur = p.stages[stage]
  if (cur && FINAL.has(cur.state)) return p
  const at = num(event.at)
  const stages = { ...p.stages }
  // Close everything before this stage.
  for (const [k] of MERGE_STAGES) {
    if (ORDER.get(k) >= ORDER.get(stage)) break
    const s = stages[k]
    if (!s) stages[k] = { state: 'skipped', startedAt: null, endedAt: null }
    else if (s.state === 'running') stages[k] = { ...s, state: 'done', endedAt: at }
  }
  const next = { ...(cur || { startedAt: null, endedAt: null }), state }
  if (next.startedAt == null && (state === 'running' || state === 'done' || state === 'failed')) next.startedAt = at
  if (FINAL.has(state)) next.endedAt = at
  const detail = cut(event.detail)
  if (detail !== undefined) next.detail = detail
  const count = cleanCount(event.count)
  if (count) next.count = count
  stages[stage] = next
  const out = { ...p, id: p.id || event.id || null, seq, stages }
  if (event.machine && typeof event.machine === 'object') out.machine = { ...p.machine, ...event.machine }
  if (num(event.estimateMs) != null && event.estimateMs > 0) out.estimateMs = event.estimateMs
  if (state === 'failed') out.outcome = 'failed'
  else if (stage === 'done' && state === 'done') out.outcome = 'merged'
  return out
}

// A merge that ended without its own last event (interrupted, given up on, merged by hand on GitHub): whatever was
// still running is closed with `state`, so no row keeps ticking on the card. Same object back when nothing ran.
export function closeRunning(progress, state, detail, at) {
  if (!progress?.stages) return progress
  let changed = false
  const stages = { ...progress.stages }
  for (const [k, s] of Object.entries(stages)) {
    if (s?.state !== 'running') continue
    stages[k] = { ...s, state, endedAt: at ?? null, ...(detail ? { detail: cut(detail) } : {}) }
    changed = true
  }
  if (!changed) return progress
  return { ...progress, stages, outcome: progress.outcome || (state === 'failed' ? 'failed' : null) }
}

// Rows for #557's CheckProgress: its icons are keyed by a check's status, its words come from `label`.
const AS_CHECK = { waiting: 'queued', running: 'running', done: 'passed', failed: 'failed', skipped: 'skipped' }

function countText(c) {
  if (!c) return ''
  return c.unit === '%' ? `${Math.round((c.done / c.total) * 100)}%` : `${c.done}/${c.total}`
}

export function mergeRuns(progress) {
  const stages = progress?.stages || {}
  return MERGE_STAGES.map(([key, label]) => {
    const s = stages[key] || { state: 'waiting', startedAt: null, endedAt: null }
    // While running, Queued says how many merges are ahead and Tests which suite and how far (short: the row is narrow).
    const extra = s.state !== 'running' ? '' : key === 'tests' ? [s.detail, countText(s.count)].filter(Boolean).join(' ') : key === 'queued' ? s.detail || '' : ''
    return {
      name: extra ? `${label} · ${extra}` : label,
      status: AS_CHECK[s.state] || 'queued',
      label: s.state,
      done: FINAL.has(s.state),
      waiting: s.state === 'waiting',
      startedAt: s.startedAt ?? null,
      completedAt: s.endedAt ?? null
    }
  })
}

// "mac-mini-1" -> "Mac mini", "macbook-pro-1" -> "MacBook Pro", "mac-mini-2012" -> "Mac mini 2012".
export function machineLabel(id) {
  if (!id || typeof id !== 'string') return 'the merge machine'
  const known = { mac: 'Mac', mini: 'mini', macbook: 'MacBook', pro: 'Pro', air: 'Air', studio: 'Studio' }
  const words = id.replace(/-1$/, '').split('-')
  if (!words.every((w) => known[w] || /^\d+$/.test(w))) return id
  return words.map((w) => known[w] || w).join(' ')
}

export function estimateLine(progress) {
  if (!progress) return null
  const where = progress.machine?.id ? machineLabel(progress.machine.id) : null
  const ms = num(progress.estimateMs)
  const usual = ms && ms > 0 ? (ms < 60_000 ? 'Usually under a minute' : `Usually about ${Math.round(ms / 60_000)} min`) : null
  if (usual && where) return `${usual} · on ${where}`
  if (usual) return usual
  return where ? `On ${where}` : null
}

export function busyLine(progress) {
  const m = progress?.machine
  if (!m?.busy) return null
  const why = m.top ? `${m.top} running` : num(m.load) != null && num(m.cores) ? `load ${m.load} on ${m.cores} cores` : 'heavily loaded'
  return `${machineLabel(m.id)} is busy (${why}); this may be slow`
}

// #567: a finished attempt (failed, sent back, interrupted) describes the commit it ran on. Once the PR has a newer
// head it no longer applies. Unknown heads keep it (never hide a failure), and a running merge is never hidden.
export function opForHead(op, head) {
  if (!op || !op.state || op.state === 'idle') return { state: 'idle' }
  // marvin#762: a queued approval is still waiting whatever the head; it is not a verdict on an older commit. So is one
  // waiting for memory (marvin#940).
  if (op.state !== 'merging' && op.state !== 'queued' && op.state !== 'waiting-memory' && head && op.head && head !== op.head) return { state: 'idle' }
  return op
}
