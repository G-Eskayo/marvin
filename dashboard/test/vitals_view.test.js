import { describe, it, expect } from 'vitest'
import {
  ageSeconds, machineOf, partFor, fixOfCheck, kindOfCheck, rowFromCheck, stepsOf, rowFromLoop, rowFromDecision,
  compareRows, needsYou, tightestBudget, verdict, columnSlice, INDEPENDENCE_KINDS
} from '../src/lib/vitals_view.js'

// Vitals mock-up (marvin#873): every "what needs you" row is built from a live check result in the #836 contract
// (reason, fix, confidence, tolerance_s, machine). Until #836 lands those fields, the row derives them from what the
// check already says, and says so.

const NOW = Date.parse('2026-11-12T17:00:00Z')
const iso = (minAgo) => new Date(NOW - minAgo * 60_000).toISOString()
const check = (id, severity, detail = '', extra = {}) => ({ id, label: id, severity, detail, checked_at: iso(2), value: null, ...extra })

describe('ageSeconds', () => {
  it('is never negative (clock skew between Macs) and null for junk', () => {
    expect(ageSeconds(iso(5), NOW)).toBe(300)
    expect(ageSeconds(new Date(NOW + 90_000).toISOString(), NOW)).toBe(0)
    expect(ageSeconds('yesterday', NOW)).toBe(null)
    expect(ageSeconds(null, NOW)).toBe(null)
  })
})

describe('machineOf', () => {
  it('prefers the #836 field, then the id suffix, then the copy host', () => {
    expect(machineOf({ id: 'disk:space@mac-mini-1', machine: 'macbook-pro-1' }, 'x')).toBe('macbook-pro-1')
    expect(machineOf({ id: 'disk:space@mac-mini-1' }, 'x')).toBe('mac-mini-1')
    expect(machineOf({ id: 'main:green' }, 'mac-mini-1')).toBe('mac-mini-1')
    expect(machineOf({ id: 'main:green' }, null)).toBe(null)
  })
})

describe('partFor', () => {
  it('puts each check in its Body region, by the regions in brain-map/enrichment.json', () => {
    expect(partFor('disk:space@mac-mini-1')).toBe('region:Body')
    expect(partFor('memory:pressure@mac-mini-1')).toBe('region:Body')
    expect(partFor('jobs:exit@mac-mini-1')).toBe('region:Body')
    expect(partFor('dispatch:parallel')).toBe('region:Pipeline')
    expect(partFor('main:green')).toBe('region:Code & tests')
    expect(partFor('contract:daily-digest')).toBe('region:Producers')
    expect(partFor('cron:tidy-agent')).toBe('region:Producers')
    expect(partFor('memory:lint')).toBe('region:Skills & tools')
    expect(partFor('route:intent-routing-collection')).toBe('region:Skills & tools')
  })
  it('puts project checks on their Work node, and says null for a part the map has no place for', () => {
    expect(partFor('profile:missing:G-Eskayo/MechanicGPT')).toBe('MechanicGPT')
    expect(partFor('purpose:missed:277')).toBe('MARVIN')
    expect(partFor('errors@mac-mini-1')).toBe(null)
    expect(partFor('something-new')).toBe(null)
    expect(partFor('')).toBe(null)
    expect(partFor(undefined)).toBe(null)
  })
})

describe('fixOfCheck', () => {
  it('uses the #836 fix when the check carries one', () => {
    expect(fixOfCheck({ fix: 'python3 lib/x.py --seed' })).toEqual({ level: 'one_tap', label: 'Run the fix', text: 'python3 lib/x.py --seed', derived: false })
    expect(fixOfCheck({ fix: { level: 'auto', text: 'cleared 3 GiB', done_at: iso(1) } })).toMatchObject({ level: 'auto', text: 'cleared 3 GiB', done: true, derived: false })
    expect(fixOfCheck({ fix: 'none' })).toEqual({ level: 'none', label: null, text: null, derived: false })
  })
  it('derives the advice from the detail until #836 lands, and marks it derived', () => {
    expect(fixOfCheck({ detail: '0 documents. Fix: python3 ~/.agents/lib/intent_classify.py --seed' })).toMatchObject({ text: 'python3 ~/.agents/lib/intent_classify.py --seed', derived: true })
    expect(fixOfCheck({ detail: 'last run failed: x (exit 1) -- read the job\'s log on this machine' })).toMatchObject({ text: "read the job's log on this machine", derived: true, level: null })
    expect(fixOfCheck({ detail: 'nothing to say' })).toEqual({ level: null, label: null, text: null, derived: true })
  })
})

describe('kindOfCheck', () => {
  it('a missed purpose is a purpose or output contract check; everything else is a failure', () => {
    expect(kindOfCheck({ id: 'purpose:missed:277' })).toBe('missed')
    expect(kindOfCheck({ id: 'contract:safety-monitor' })).toBe('missed')
    expect(kindOfCheck({ id: 'disk:space@mac-mini-1' })).toBe('failure')
  })
})

describe('rowFromCheck', () => {
  it('carries reason, age, Mac and fix (the #836 row contract)', () => {
    const r = rowFromCheck(check('disk:space@mac-mini-1', 'red', '4 GiB free of 228 (2%) -- check ~/.claude/logs/mr-pipeline-sweep.md'), { host: 'mac-mini-1', now: NOW })
    expect(r).toMatchObject({ key: 'check:disk:space@mac-mini-1', kind: 'failure', severity: 'red', machine: 'mac-mini-1', ageS: 120, part: 'region:Body', source: 'check' })
    expect(r.reason).toBe('4 GiB free of 228 (2%)')
    expect(r.fix.text).toBe('check ~/.claude/logs/mr-pipeline-sweep.md')
  })
  it('uses the #836 reason when present, and marks a check older than its tolerance as stale', () => {
    const r = rowFromCheck(check('main:green', 'red', 'long detail', { reason: 'main fails 2 tests', tolerance_s: 60, checked_at: iso(10) }), { now: NOW })
    expect(r.reason).toBe('main fails 2 tests')
    expect(r.stale).toBe(true)
    expect(rowFromCheck(check('main:green', 'red', 'x'), { now: NOW, toleranceS: 1200 }).stale).toBe(false)
  })
  it('a red check with fix "none" is a decision, in amber (#836 rule)', () => {
    const r = rowFromCheck(check('profile:missing:G-Eskayo/MechanicGPT', 'red', 'no profile', { fix: 'none' }), { now: NOW })
    expect(r.kind).toBe('decision')
    expect(r.severity).toBe('yellow')
  })
  it("couldn't measure is unknown, never green", () => {
    const r = rowFromCheck(check('dispatch:parallel', 'unknown', "couldn't measure: timed out after 60 s", { measured: false }), { now: NOW })
    expect(r.severity).toBe('unknown')
    expect(r.confidence).toBe("couldn't measure")
  })
  it('returns null for green checks and for junk', () => {
    expect(rowFromCheck(check('x', 'green'), { now: NOW })).toBe(null)
    expect(rowFromCheck(null, { now: NOW })).toBe(null)
    expect(rowFromCheck({ severity: 'red' }, { now: NOW })).toBe(null)
  })
})

describe('stepsOf (which step of the loop failed)', () => {
  it('watched red: noticed, not fixed', () => {
    expect(stepsOf({ status: 'broken', watched: { state: 'red' }, verified: { state: 'green' } })).toEqual({ notice: 'ok', act: 'failed', verify: 'unknown', told: 'unknown', failed: 'act' })
  })
  it('verify red: the fix ran but did not verify', () => {
    expect(stepsOf({ status: 'broken', watched: { state: 'green' }, verified: { state: 'red' } })).toMatchObject({ notice: 'ok', act: 'ok', verify: 'failed', failed: 'verify' })
  })
  it('stalled with no full cycle: act', () => {
    expect(stepsOf({ status: 'stalled', watched: { state: 'green' }, verified: { state: 'green' }, reason: 'no full cycle in 1 day(s)' }).failed).toBe('act')
  })
  it('a closed loop has no failed step', () => {
    expect(stepsOf({ status: 'closed', watched: { state: 'green' }, verified: { state: 'green' } }).failed).toBe(null)
  })
})

describe('rowFromLoop', () => {
  const loop = { id: 'health-sweep', name: 'Health checks run and report', status: 'broken', watches: 'check:jobs:exit', reason: 'jobs:exit@macbook-pro-1: last run failed',
    fix: { level: 'one_tap', kind: 'rerun', arg: 'health-check' }, watched: { state: 'red' }, verified: { state: 'yellow' }, owner: 'marvin' }
  it('one row per broken loop, with its fix button at its fix level', () => {
    const r = rowFromLoop(loop, { now: NOW, healthAt: iso(30) })
    expect(r).toMatchObject({ key: 'loop:health-sweep', kind: 'failure', severity: 'red', source: 'loop', title: 'Health checks run and report' })
    expect(r.fix).toMatchObject({ level: 'one_tap', label: 'Re-run', action: { type: 'loop', id: 'health-sweep' } })
    expect(r.steps.failed).toBe('act')
    expect(r.ageS).toBe(1800)
  })
  it('a paused loop is a paused row with Resume now', () => {
    const r = rowFromLoop({ ...loop, status: 'paused', reason: 'Paused: resumes when portfolio #21 merges' }, { now: NOW })
    expect(r.kind).toBe('paused')
    expect(r.fix.label).toBe('Resume now')
  })
  it('closed and not-wired loops are not rows', () => {
    expect(rowFromLoop({ ...loop, status: 'closed' }, { now: NOW })).toBe(null)
    expect(rowFromLoop({ ...loop, status: 'not_wired' }, { now: NOW })).toBe(null)
  })
})

describe('rowFromDecision', () => {
  it('a Workshop item waiting on Gil\'s answers is a decision row that opens the item', () => {
    const r = rowFromDecision({ key: 'o/marvin#977', repo: 'o/marvin', number: 977, type: 'pr', title: 'Accounts', project: 'marvin', since: NOW - 3_600_000, step: { verb: 'Answer 2 decisions' } }, { now: NOW })
    // its part is the project's Work node, named by its registry id (the map resolves project:<id>)
    expect(r).toMatchObject({ kind: 'decision', severity: 'yellow', title: 'Accounts', reason: 'Answer 2 decisions', ageS: 3600, part: 'project:marvin' })
    expect(r.fix).toMatchObject({ level: 'decision', action: { type: 'item', repo: 'o/marvin', number: 977, kind: 'pr' } })
    expect(rowFromDecision({ repo: 'o/x', number: 1, step: { verb: 'Answer 1 decision' } }, { now: NOW }).part).toBe(null)
  })
  it('anything that is not an answer to give is not a decision row', () => {
    expect(rowFromDecision({ step: { verb: 'Approve' } }, { now: NOW })).toBe(null)
    expect(rowFromDecision(null, { now: NOW })).toBe(null)
  })
})

describe('compareRows (worst first)', () => {
  it('failures, then missed purposes, then decisions, then paused; red before unknown before amber; older first', () => {
    const rows = [
      { key: 'd', kind: 'decision', severity: 'yellow', ageS: 10 },
      { key: 'p', kind: 'paused', severity: 'yellow', ageS: 10 },
      { key: 'm', kind: 'missed', severity: 'red', ageS: 10 },
      { key: 'fy', kind: 'failure', severity: 'yellow', ageS: 10 },
      { key: 'fu', kind: 'failure', severity: 'unknown', ageS: 10 },
      { key: 'fr-new', kind: 'failure', severity: 'red', ageS: 10 },
      { key: 'fr-old', kind: 'failure', severity: 'red', ageS: 999 },
      { key: 'fr-noage', kind: 'failure', severity: 'red', ageS: null }
    ]
    expect([...rows].sort(compareRows).map((r) => r.key)).toEqual(['fr-old', 'fr-new', 'fr-noage', 'fu', 'fy', 'm', 'd', 'p'])
  })
})

describe('needsYou', () => {
  const health = { checks: [
    check('disk:space@mac-mini-1', 'red', 'low'),
    check('jobs:exit@mac-mini-1', 'red', 'failed'),
    check('contract:daily-digest', 'yellow', 'past deadline'),
    check('memory:lint', 'yellow', '4 broken links'),
    check('token:gh-token', 'green', 'ok')
  ], copy: { host: 'mac-mini-1', ageS: 60, stale: false } }
  const loops = { health_at: iso(30), loops: [{ id: 'health-sweep', name: 'Health checks run and report', status: 'broken', watches: 'check:jobs:exit', reason: 'r', fix: { level: 'one_tap', kind: 'rerun' }, watched: { state: 'red' }, verified: { state: 'green' } }] }

  it('a loop absorbs the checks it watches: one row per problem, the checks listed under it', () => {
    const v = needsYou({ health, loops, decisions: [], now: NOW })
    // both red failures; the loop's judgement (30 min) is older than the disk check (2 min), so it comes first
    expect(v.rows.map((r) => r.key)).toEqual(['loop:health-sweep', 'check:disk:space@mac-mini-1', 'check:contract:daily-digest'])
    const loopRow = v.rows.find((r) => r.key === 'loop:health-sweep')
    expect(loopRow.parts.map((p) => p.key)).toEqual(['check:jobs:exit@mac-mini-1'])
    // the loop's own judgement is as old as the health file loops.py read, whatever the checks under it say; its Mac is
    // the one those checks are about
    expect(loopRow.machine).toBe('mac-mini-1')
    expect(loopRow.ageS).toBe(1800)
    expect(loopRow.stale).toBe(true)
  })
  it('a loop judged on a fresh health file is not stale', () => {
    const v = needsYou({ health, loops: { ...loops, health_at: iso(5) }, decisions: [], now: NOW })
    expect(v.rows.find((r) => r.key === 'loop:health-sweep').stale).toBe(false)
  })
  it('a check with no time of its own is as old as the snapshot it came in', () => {
    const v = needsYou({ health: { checks: [{ id: 'contract:safety-monitor', label: 'x', severity: 'red', detail: 'waiting' }], copy: { host: 'mac-mini-1', ageS: 300, stale: false } }, now: NOW })
    expect(v.rows[0].ageS).toBe(300)
  })
  it('amber checks that are not missed purposes are "also watching", not in the column', () => {
    const v = needsYou({ health, loops, decisions: [], now: NOW })
    expect(v.watching.map((r) => r.key)).toEqual(['check:memory:lint'])
    expect(v.counts).toEqual({ failure: 2, missed: 1, decision: 0, paused: 0 })
  })
  it('nothing wrong: no rows', () => {
    const v = needsYou({ health: { checks: [check('a', 'green')] }, loops: { loops: [] }, decisions: [], now: NOW })
    expect(v.rows).toEqual([])
    expect(v.watching).toEqual([])
  })
  it('missing or broken sources never throw (map not loaded, loops unreadable)', () => {
    expect(needsYou({}).rows).toEqual([])
    expect(needsYou({ health: { checks: 'nope' }, loops: { loops: null }, decisions: 5 }).rows).toEqual([])
  })
  it('60 problems: all kept, sorted, and the counts add up', () => {
    const many = { checks: Array.from({ length: 60 }, (_, i) => check(`disk:space@m${i}`, i % 2 ? 'red' : 'unknown', 'x', { checked_at: iso(i) })) }
    const v = needsYou({ health: many, loops: { loops: [] }, decisions: [], now: NOW })
    expect(v.rows).toHaveLength(60)
    expect(v.rows[0].severity).toBe('red')
    expect(v.rows[29].severity).toBe('red')
    expect(v.rows[30].severity).toBe('unknown')
    expect(v.counts.failure).toBe(60)
  })
  it('the same check twice (two Macs reported it) is one row', () => {
    const dup = { checks: [check('main:green', 'red', 'a'), check('main:green', 'red', 'b')] }
    expect(needsYou({ health: dup, now: NOW }).rows).toHaveLength(1)
  })
})

describe('columnSlice', () => {
  it('shows the first n, and says how many more', () => {
    const rows = Array.from({ length: 60 }, (_, i) => ({ key: String(i) }))
    expect(columnSlice(rows, 12)).toMatchObject({ shown: rows.slice(0, 12), more: 48 })
    expect(columnSlice(rows, Infinity).more).toBe(0)
    expect(columnSlice([], 12)).toEqual({ shown: [], more: 0 })
  })
})

describe('tightestBudget', () => {
  // resets_at in epoch seconds, as the plan's own meter reports it (lib/plan_usage.py)
  const at = (h) => Math.round((NOW + h * 3_600_000) / 1000)
  it('the fullest window, its reset, its line and its pace', () => {
    const b = tightestBudget({ ts: iso(1), five_hour: { used_percentage: 30, resets_at: at(2) }, seven_day: { used_percentage: 75, resets_at: at(24) } }, NOW)
    expect(b).toMatchObject({ label: 'Weekly', pct: 75, line: 'ok' })
    expect(b.resetsAt).toBe(at(24) * 1000)
    // 6 of 7 days gone, 75% used: on pace for 87.5%
    expect(b.pace).toBe(88)
  })
  it('soft line at 90, hard at 99', () => {
    expect(tightestBudget({ five_hour: { used_percentage: 91, resets_at: at(1) } }, NOW).line).toBe('soft')
    expect(tightestBudget({ five_hour: { used_percentage: 99.5, resets_at: at(1) } }, NOW).line).toBe('hard')
  })
  it('a window whose reset has passed is not a reading; nothing is "not enough data", never 0%', () => {
    expect(tightestBudget({ five_hour: { used_percentage: 99, resets_at: at(-1) } }, NOW)).toBe(null)
    expect(tightestBudget(null, NOW)).toBe(null)
    expect(tightestBudget({ five_hour: { used_percentage: 'lots' } }, NOW)).toBe(null)
  })
})

describe('verdict', () => {
  const budget = { label: 'Weekly', pct: 75, line: 'ok', resetsAt: NOW + 86_400_000, pace: 88 }
  it('healthy when nothing needs Gil', () => {
    const v = verdict({ rows: [], watching: [], health: { copy: { host: 'mac-mini-1', ageS: 60, stale: false } }, budget, now: NOW })
    expect(v).toMatchObject({ healthy: true, headline: 'Healthy', stale: false, from: 'mac-mini-1', ageS: 60 })
  })
  it('counts what needs Gil, worst kind first', () => {
    const v = verdict({ rows: [{ kind: 'failure' }, { kind: 'failure' }, { kind: 'decision' }], watching: [{}], health: { copy: { ageS: 60 } }, budget, now: NOW })
    expect(v.headline).toBe('3 things need you')
    expect(v.detail).toBe('2 failures · 1 decision · 1 watching')
    expect(v.healthy).toBe(false)
  })
  it('a stale verdict says so and is never "Healthy"', () => {
    const v = verdict({ rows: [], watching: [], health: { copy: { host: 'mac-mini-1', ageS: 3 * 3600, stale: true } }, budget, now: NOW })
    expect(v.stale).toBe(true)
    expect(v.healthy).toBe(false)
    expect(v.headline).toBe('No fresh reading')
  })
  it('no health at all: not enough data, never healthy', () => {
    expect(verdict({ now: NOW }).headline).toBe('No fresh reading')
  })
  it('Independence per kind of work: not enough data yet until #875 measures it', () => {
    const v = verdict({ rows: [], health: { copy: { ageS: 1 } }, now: NOW })
    expect(v.independence.map((k) => k.kind)).toEqual(INDEPENDENCE_KINDS)
    expect(v.independence.every((k) => k.text === 'not enough data yet')).toBe(true)
    const w = verdict({ rows: [], health: { copy: { ageS: 1 } }, independence: { Embeddings: 1, Coding: 0 }, now: NOW })
    expect(w.independence.find((k) => k.kind === 'Embeddings').text).toBe('100% local')
    expect(w.independence.find((k) => k.kind === 'Coding').text).toBe('0% local')
  })
})
