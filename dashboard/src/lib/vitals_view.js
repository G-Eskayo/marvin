// Vitals tab mock-up (marvin#873): the verdict line and the "what needs you" column, built from live results.
// Spec: marvin-instance docs/plans/vitals-v5-2026-10-30.md (refresh 2026-11-04: loops are the unit); terms in CONTEXT.md
// "Vitals (v5 grilling…)". Pure, no I/O. O(C + L·C) for C checks and L loops (each loop scans the checks once).
//
// The row contract is #836's: reason, fix, confidence, tolerance and the reporting Mac. Where a check already carries
// those fields they are used as they are; until #836 lands, they are read from what the check says today (the id's
// "@<mac>" suffix, the copy's host, the advice after "Fix:" or " -- " in its detail) and the fix is marked `derived`.
import { FIX_LABEL } from './loops_view.js'

export const KIND_ORDER = ['failure', 'missed', 'decision', 'paused']
const SEVERITY_ORDER = ['red', 'unknown', 'yellow']
const NOT_A_ROW = new Set(['green', 'unmonitored'])

// The kinds of work Independence is measured for (CONTEXT.md "Independence"). #875 measures them; until then each
// says "not enough data yet", never 0%.
export const INDEPENDENCE_KINDS = ['Coding', 'Research', 'Review', 'Embeddings', 'Transcription', 'Voice']

export function ageSeconds(isoText, now = Date.now()) {
  const t = Date.parse(isoText || '')
  if (!Number.isFinite(t)) return null
  return Math.max(0, Math.round((now - t) / 1000))
}

// The reporting Mac: #836's field, else the "@<mac>" in a per-machine check id, else the Mac that wrote the snapshot.
export function machineOf(c, host = null) {
  if (c && typeof c.machine === 'string' && c.machine) return c.machine
  const m = /@([A-Za-z0-9._-]+)$/.exec(String(c?.id || ''))
  return m ? m[1] : host || null
}

// Where a row's part sits on the map (Body and Work layout, brain-map ?layout=work). The regions and what belongs in
// each are brain-map/enrichment.json's body_regions; a project's checks go to its Work node. null: the map has no
// part for it yet, and the row says so instead of lighting the wrong thing.
const REGION_BY_PREFIX = [
  [['disk', 'jobs', 'machine', 'thermal', 'cpu', 'swap', 'headroom', 'desktoplive'], 'region:Body'],
  [['dispatch', 'lock', 'breaker', 'tickets', 'queue', 'pipeline', 'token'], 'region:Pipeline'],
  [['gh', 'github', 'gate', 'rate'], 'region:GitHub'],
  [['main', 'dashboard', 'webhook', 'triggers', 'build', 'tests'], 'region:Code & tests'],
  [['route', 'tools', 'hooks', 'skills', 'memory', 'graphify', 'intent'], 'region:Skills & tools'],
  [['sync', 'code-sync', 'peer', 'heartbeat', 'reach'], 'region:Code sync'],
  [['contract', 'cron', 'catalog', 'tagger', 'digest', 'producer', 'research'], 'region:Producers'],
  [['usage', 'plan', 'credit', 'energy'], 'region:Energy']
]
const PREFIX_PART = new Map(REGION_BY_PREFIX.flatMap(([prefixes, part]) => prefixes.map((p) => [p, part])))

export function partFor(id) {
  const s = String(id || '')
  if (!s) return null
  const project = /^profile:missing:[^/]+\/(.+)$/.exec(s)
  if (project) return project[1]
  if (/^purpose:missed:/.test(s)) return 'MARVIN'
  if (/^memory:pressure/.test(s)) return 'region:Body'
  return PREFIX_PART.get(s.split(/[:@]/)[0]) || null
}

const LEVEL_LABEL = { auto: 'Fixed by MARVIN', one_tap: 'Run the fix', decision: 'Decide' }

// A check's fix at its fix level (auto, one tap, decision; "none" when there is no fix). The #836 field when present.
export function fixOfCheck(c) {
  const f = c?.fix
  if (f === 'none') return { level: 'none', label: null, text: null, derived: false }
  if (typeof f === 'string' && f.trim()) return { level: 'one_tap', label: LEVEL_LABEL.one_tap, text: f.trim(), derived: false }
  if (f && typeof f === 'object') {
    const level = ['auto', 'one_tap', 'decision', 'none'].includes(f.level) ? f.level : 'one_tap'
    return { level, label: f.label || LEVEL_LABEL[level] || null, text: f.text || f.command || null, done: !!f.done_at, derived: false }
  }
  const d = String(c?.detail || '')
  const m = /\bFix:\s*(.+)$/s.exec(d) || /\s--\s(.+)$/s.exec(d)
  return { level: null, label: null, text: m ? m[1].trim() : null, derived: true }
}

function reasonOf(c) {
  if (typeof c.reason === 'string' && c.reason.trim()) return c.reason.trim()
  const d = String(c.detail || '')
  return d.split(/\s--\s|\s*\bFix:/)[0].trim() || d
}

export function kindOfCheck(c) {
  return /^(purpose:missed|contract):/.test(String(c?.id || '')) ? 'missed' : 'failure'
}

export function rowFromCheck(c, { host = null, now = Date.now(), toleranceS = null, snapshotAgeS = null } = {}) {
  if (!c || typeof c.id !== 'string' || !c.id) return null
  const sev = c.severity === 'grey' ? 'unknown' : c.severity
  if (NOT_A_ROW.has(sev) || !SEVERITY_ORDER.includes(sev)) return null
  const fix = fixOfCheck(c)
  let kind = kindOfCheck(c)
  let severity = sev
  // #836: a check with no fix can't be red; it is amber and listed for a decision.
  if (fix.level === 'none' && sev === 'red') { kind = 'decision'; severity = 'yellow' }
  // A check with no time of its own (an output contract's finding) is as old as the snapshot it came in.
  const ageS = ageSeconds(c.checked_at, now) ?? (Number.isFinite(snapshotAgeS) ? snapshotAgeS : null)
  const tol = Number.isFinite(c.tolerance_s) ? c.tolerance_s : Number.isFinite(toleranceS) ? toleranceS : null
  return {
    key: `check:${c.id}`, source: 'check', sourceId: c.id, kind, severity, title: c.label || c.id, reason: reasonOf(c),
    fix, machine: machineOf(c, host), checkedAt: c.checked_at || null, ageS, stale: tol != null && ageS != null && ageS > tol,
    confidence: c.confidence || (c.measured === false || sev === 'unknown' ? "couldn't measure" : 'measured'),
    part: partFor(c.id), detail: String(c.detail || ''), value: c.value ?? null, parts: []
  }
}

// Which of the loop's four steps (notice, act, verify, told you) failed, from lib/loops.py's evaluate(): a red watched
// signal was noticed and not fixed; a red verify means the fix ran and didn't hold; failed runs or no full cycle is act.
// "Told you" has no signal yet (#1132's delivery results), so it says unknown rather than guessing.
export function stepsOf(loop) {
  const s = { notice: 'ok', act: 'ok', verify: 'ok', told: 'unknown', failed: null }
  if (!loop || (loop.status !== 'broken' && loop.status !== 'stalled')) {
    return loop?.status === 'closed' ? s : { notice: 'unknown', act: 'unknown', verify: 'unknown', told: 'unknown', failed: null }
  }
  if (loop.status === 'broken' && loop.watched?.state !== 'red' && loop.verified?.state === 'red') return { ...s, verify: 'failed', failed: 'verify' }
  return { ...s, act: 'failed', verify: 'unknown', failed: 'act' }
}

// lib/loops.py judges every loop from the health file it read; past the sweep's tolerance (health_checks.py
// STATUS_TOLERANCE_S, 20 min) that judgement is old, and the row says so.
export const LOOP_TOLERANCE_S = 20 * 60

const checkPrefix = (signal) => (typeof signal === 'string' && signal.startsWith('check:') ? signal.slice(6) : null)

export function rowFromLoop(loop, { now = Date.now(), healthAt = null } = {}) {
  if (!loop || typeof loop.id !== 'string') return null
  const base = { key: `loop:${loop.id}`, source: 'loop', sourceId: loop.id, title: loop.name || loop.id, reason: String(loop.reason || ''),
    machine: null, checkedAt: healthAt, ageS: ageSeconds(healthAt, now), stale: (ageSeconds(healthAt, now) ?? Infinity) > LOOP_TOLERANCE_S, confidence: 'measured',
    part: partFor(checkPrefix(loop.watches) || checkPrefix(loop.verify)), detail: String(loop.reason || ''), value: null, parts: [],
    watches: [checkPrefix(loop.watches), checkPrefix(loop.verify)].filter(Boolean), ticket: loop.ticket ?? null }
  if (loop.status === 'paused') {
    return { ...base, kind: 'paused', severity: 'yellow', steps: stepsOf(loop), fix: { level: 'one_tap', label: 'Resume now', text: null, action: { type: 'loop', id: loop.id }, derived: false } }
  }
  if (loop.status !== 'broken' && loop.status !== 'stalled') return null
  const kindOfFix = loop.fix?.kind
  return {
    ...base,
    kind: kindOfFix === 'decision' ? 'decision' : 'failure',
    severity: loop.status === 'broken' ? 'red' : 'yellow',
    steps: stepsOf(loop),
    fix: FIX_LABEL[kindOfFix]
      ? { level: loop.fix.level || 'one_tap', label: FIX_LABEL[kindOfFix], text: null, action: { type: 'loop', id: loop.id }, derived: false }
      : { level: null, label: null, text: null, derived: false }
  }
}

const DECISION_VERB = /^Answer \d+ decisions?/

// A Workshop item (next_step.js buildNow) whose next step is Gil's answers.
export function rowFromDecision(item, { now = Date.now() } = {}) {
  if (!item || !DECISION_VERB.test(String(item.step?.verb || ''))) return null
  const repo = item.repo || null
  return {
    key: `decision:${item.key || `${repo}#${item.number}`}`, source: 'decision', sourceId: item.key || null, kind: 'decision', severity: 'yellow',
    title: item.title || `${repo}#${item.number}`, reason: item.step.verb, machine: null,
    checkedAt: Number.isFinite(item.since) ? new Date(item.since).toISOString() : null,
    ageS: Number.isFinite(item.since) ? Math.max(0, Math.round((now - item.since) / 1000)) : null, stale: false, confidence: 'measured',
    part: item.project ? `project:${item.project}` : null, detail: '', value: null, parts: [],
    fix: { level: 'decision', label: 'Answer', text: null, action: { type: 'item', repo, number: item.number, kind: item.type === 'pr' ? 'pr' : 'ticket' }, derived: false }
  }
}

const rank = (list, v) => { const i = list.indexOf(v); return i < 0 ? list.length : i }

// Worst first: failures, missed purposes, decisions, paused; within each red, couldn't-measure, amber; older first.
export function compareRows(a, b) {
  return rank(KIND_ORDER, a.kind) - rank(KIND_ORDER, b.kind)
    || rank(SEVERITY_ORDER, a.severity) - rank(SEVERITY_ORDER, b.severity)
    || (b.ageS ?? -1) - (a.ageS ?? -1)
    || String(a.key).localeCompare(String(b.key))
}

const arr = (v) => (Array.isArray(v) ? v : [])

export function needsYou({ health = null, loops = null, decisions = [], now = Date.now() } = {}) {
  const host = health?.copy?.host || health?.host || null
  const toleranceS = Number.isFinite(health?.copy?.toleranceS) ? health.copy.toleranceS : null
  const snapshotAgeS = Number.isFinite(health?.copy?.ageS) ? health.copy.ageS : ageSeconds(health?.generated_at, now)
  const seen = new Set()
  const checkRows = []
  for (const c of arr(health?.checks)) {
    const r = rowFromCheck(c, { host, now, toleranceS, snapshotAgeS })
    if (!r || seen.has(r.key)) continue
    seen.add(r.key)
    checkRows.push(r)
  }
  // A loop is the unit: the checks it watches fold into its row (one row per problem), listed under it.
  const absorbed = new Set()
  const loopRows = []
  for (const lp of arr(loops?.loops)) {
    const r = rowFromLoop(lp, { now, healthAt: loops?.health_at || null })
    if (!r || seen.has(r.key)) continue
    seen.add(r.key)
    const parts = checkRows.filter((c) => !absorbed.has(c.key) && r.watches.some((p) => c.sourceId.startsWith(p)))
    parts.forEach((p) => absorbed.add(p.key))
    // The checks keep their own Mac and age; the loop's row keeps the age of its own judgement (see LOOP_TOLERANCE_S).
    if (parts.length) {
      const freshest = [...parts].sort((a, b) => (a.ageS ?? Infinity) - (b.ageS ?? Infinity))[0]
      Object.assign(r, { parts, machine: freshest.machine, part: r.part || freshest.part })
    }
    loopRows.push(r)
  }
  const decisionRows = arr(decisions).map((d) => rowFromDecision(d, { now })).filter((r) => r && !seen.has(r.key) && seen.add(r.key))
  const open = checkRows.filter((r) => !absorbed.has(r.key))
  // Amber that is neither a missed purpose nor a decision is degraded, not broken: counted, kept out of the column.
  const watching = open.filter((r) => r.kind === 'failure' && r.severity === 'yellow').sort(compareRows)
  const rows = [...open.filter((r) => !watching.includes(r)), ...loopRows, ...decisionRows].sort(compareRows)
  const counts = Object.fromEntries(KIND_ORDER.map((k) => [k, rows.filter((r) => r.kind === k).length]))
  return { rows, watching, counts }
}

export function columnSlice(rows, limit) {
  const list = arr(rows)
  const shown = Number.isFinite(limit) ? list.slice(0, Math.max(0, limit)) : list
  return { shown, more: list.length - shown.length }
}

const WINDOWS = [['seven_day', 'Weekly', 7 * 86_400_000], ['five_hour', '5-hour', 5 * 3_600_000]]

// The tightest of the plan's own meters (lib/plan_usage.py's row: used % and reset in epoch seconds), with its line
// (soft about 90, hard about 99) and pace: where it lands at the reset if use keeps its rate. A window past its reset
// is no reading at all; no reading is null ("not enough data"), never 0%.
export function tightestBudget(row, now = Date.now()) {
  let best = null
  for (const [key, label, windowMs] of WINDOWS) {
    const w = row?.[key]
    const pct = Number(w?.used_percentage)
    const resetsAt = Number(w?.resets_at) * 1000
    if (!w || !Number.isFinite(pct) || !Number.isFinite(resetsAt) || resetsAt <= now) continue
    if (best && best.pct >= pct) continue
    const elapsed = 1 - (resetsAt - now) / windowMs
    best = { key, label, pct, resetsAt, line: pct >= 99 ? 'hard' : pct >= 90 ? 'soft' : 'ok', pace: elapsed > 0.02 ? Math.round(pct / elapsed) : null }
  }
  return best
}

const KIND_WORDS = { failure: ['failure', 'failures'], missed: ['missed purpose', 'missed purposes'], decision: ['decision', 'decisions'], paused: ['paused', 'paused'] }

export function verdict({ rows = [], watching = [], health = null, budget = null, independence = null, now = Date.now() } = {}) {
  const copy = health?.copy || null
  const ageS = Number.isFinite(copy?.ageS) ? copy.ageS : ageSeconds(health?.generated_at, now)
  const stale = !health || ageS == null || !!copy?.stale
  const list = arr(rows)
  const n = list.length
  const headline = stale ? 'No fresh reading' : n === 0 ? 'Healthy' : `${n} thing${n === 1 ? '' : 's'} need${n === 1 ? 's' : ''} you`
  const parts = KIND_ORDER.map((k) => [k, list.filter((r) => r.kind === k).length]).filter(([, c]) => c)
    .map(([k, c]) => `${c} ${KIND_WORDS[k][c === 1 ? 0 : 1]}`)
  if (arr(watching).length) parts.push(`${watching.length} watching`)
  const ind = INDEPENDENCE_KINDS.map((kind) => {
    const v = independence?.[kind]
    return { kind, value: Number.isFinite(v) ? v : null, text: Number.isFinite(v) ? `${Math.round(v * 100)}% local` : 'not enough data yet' }
  })
  return { healthy: !stale && n === 0, headline, detail: parts.join(' · '), stale, ageS, from: copy?.host || health?.host || null, budget, independence: ind }
}
