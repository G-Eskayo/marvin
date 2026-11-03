// Plan usage + the one throttle switch (marvin#872). Mock-up logic only, no DOM: every word the card shows, from one
// plan-usage reading, the switch's position and what is running. The page (index.html) and the tests
// (dashboard/test/usage_toggle_proto.test.js) both call describeThrottle(), so what you see in the mock-up is what is
// tested.
//
// A classic script, not a module, so the page opens inside MARVIN's sandboxed mock-up window with no build. It sets
// globalThis.UsageToggle.
//
// Input (plain data):
//   usage:    one line of ~/.claude/logs/plan-usage.jsonl (#872 slice 1), or null before the first one:
//             { recorded_at, five_hour: { used_pct, resets_at }, seven_day: { used_pct, resets_at },
//               windows: [{ start, end, peak_pct, hit_limit }], weekly_pace }
//             weekly_pace = the week's projected used % at its reset (sample shape; the recorder decides the real one)
//   on:       the switch
//   running:  [{ title, kind: 'build'|'fix' }]   what is running now
//   queued:   ready tickets waiting
//   slots:    { max }   what the Macs hold at once (config/dispatch.json, capped by machine_slots)
//   guards:   { min_disk_gb, min_github_budget_pct }   the fixed guards (config/dispatch.json)
//   lastStep: the step from the last good reading, kept while the reading is stale
//   now:      ms
//
// Output: { step, reading, five, week, pace, heldBy, newWork, perMac, headline, doing, guardrails, flip }
;(function (root) {
  'use strict'

  const LINES = { soft: 90, warn: 95, hard: 99 }
  const STALE_MS = 15 * 60_000
  const RANK = { clear: 0, soft: 1, warn: 2, hard: 3 }
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

  const num = (x) => (typeof x === 'number' && Number.isFinite(x) && x >= 0 ? x : null)
  const time = (ms) => {
    if (ms == null || !Number.isFinite(ms)) return null
    const d = new Date(ms)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  const when = (ms, now) => {
    if (ms == null || !Number.isFinite(ms)) return null
    return ms - now < 20 * 3600_000 ? time(ms) : `${DAYS[new Date(ms).getDay()]} ${time(ms)}`
  }
  const span = (ms) => {
    const m = Math.max(0, Math.round(ms / 60_000))
    if (m < 60) return `${m} min`
    const h = Math.floor(m / 60)
    if (h < 48) return `${h} h${m % 60 && h < 5 ? ` ${m % 60} min` : ''}`
    return `${Math.round(h / 24)} days`
  }
  const round = (x) => (x == null ? null : Math.round(x))

  function stepOf(pct) {
    const p = num(pct)
    if (p == null) return null
    if (p >= LINES.hard) return 'hard'
    if (p >= LINES.warn) return 'warn'
    if (p >= LINES.soft) return 'soft'
    return 'clear'
  }

  // The week's projected use at its reset: under it pulls queued work forward, over it slows it.
  function paceOf(projected) {
    const p = num(projected)
    if (p == null) return 'unknown'
    if (p > 100) return 'over'
    if (p >= LINES.soft) return 'on'
    return 'under'
  }

  // One budget (the 5-hour window or the week) as the card shows it.
  function budget(b, now, label) {
    const pct = num(b && b.used_pct)
    const resetsAt = b && b.resets_at ? Date.parse(b.resets_at) : NaN
    if (pct == null) return { label, pct: null, step: null, resetsAt: null, text: 'not enough data yet' }
    if (Number.isFinite(resetsAt) && resetsAt <= now) {
      return { label, pct: null, step: 'clear', resetsAt, text: `reset at ${time(resetsAt)} · new reading due` }
    }
    const at = Number.isFinite(resetsAt) ? resetsAt : null
    return {
      label, pct, step: stepOf(pct), resetsAt: at,
      text: `${round(pct)}%${at ? ` · resets ${when(at, now)} (in ${span(at - now)})` : ''}`
    }
  }

  function windowsSummary(list) {
    const ws = Array.isArray(list) ? list.filter((w) => w && num(w.peak_pct) != null) : []
    if (!ws.length) return { total: 0, hitLimit: 0, unused: 0, leftPct: null, text: 'not enough data yet' }
    const hitLimit = ws.filter((w) => w.hit_limit || w.peak_pct >= 100).length
    const unused = ws.filter((w) => w.peak_pct < 10).length
    const leftPct = Math.round(ws.reduce((s, w) => s + Math.max(0, LINES.hard - w.peak_pct), 0) / ws.length)
    return {
      total: ws.length, hitLimit, unused, leftPct,
      text: `${ws.length} windows: ${hitLimit} hit the limit, ${unused} left unused, about ${leftPct}% left on the table per window`
    }
  }

  function describeThrottle({ usage, on, running = [], queued = 0, slots = { max: 1 }, guards = {}, lastStep = null, now = Date.now() } = {}) {
    const max = Math.max(1, num(slots && slots.max) || 1)
    const g = { disk: num(guards.min_disk_gb) ?? 15, gh: num(guards.min_github_budget_pct) ?? 20 }
    const recordedAt = usage && usage.recorded_at ? Date.parse(usage.recorded_at) : NaN
    const reading = !usage ? 'none' : !Number.isFinite(recordedAt) || now - recordedAt > STALE_MS ? 'stale' : 'fresh'

    const five = budget(usage && usage.five_hour, now, 'plan 5-hour window')
    const week = budget(usage && usage.seven_day, now, 'plan week')
    const pace = paceOf(usage && usage.weekly_pace)
    const windows = windowsSummary(usage && usage.windows)

    // The tighter budget decides. A stale reading keeps the last known step; nothing known is "unknown", never clear.
    let step
    if (reading === 'fresh') {
      const steps = [five.step, week.step].filter(Boolean)
      step = steps.length ? steps.reduce((a, b) => (RANK[b] > RANK[a] ? b : a)) : 'unknown'
    } else {
      step = reading === 'stale' && RANK[lastStep] != null ? lastStep : 'unknown'
    }
    const tight = [five, week].filter((b) => b.pct != null).sort((a, b) => b.pct - a.pct)[0] || null
    const heldBy = step === 'unknown' ? 'no plan reading' : step === 'clear' || !tight ? null : `${tight.label} ${round(tight.pct)}%`
    const resetOf = tight && tight.resetsAt ? when(tight.resetsAt, now) : null

    const holds = step === 'hard'
    const perMac = !on || step === 'unknown'
    const newWork = holds ? 0 : perMac ? 1 : max
    const fixes = running.filter((r) => r.kind === 'fix').length
    const n = running.length

    const doing = []
    if (reading === 'stale') doing.push(`The plan reading is ${span(now - recordedAt)} old: keeping the last known step, never assuming 0%.`)
    if (step === 'unknown') doing.push('No plan reading yet: one ticket per Mac, and the fixed guards decide.')
    if (holds) {
      doing.push(`Nothing new starts${resetOf ? ` until ${resetOf}` : ''}.`)
      const builds = n - fixes
      if (builds) doing.push(builds === 1 ? 'The running build finishes.' : `The ${builds} running builds finish.`)
      doing.push(`Fix work still runs${fixes ? ` (${fixes} now)` : ''}: it is what frees room.`)
      doing.push('In your sessions, a big task needs your yes; small replies keep working.')
    } else if (step === 'clear') {
      doing.push(perMac ? 'One ticket at a time on each Mac.' : `Up to ${max} tickets at once.`)
      doing.push('Background jobs run as normal.')
    } else if (step === 'soft' || step === 'warn') {
      doing.push(perMac ? 'One ticket at a time on each Mac.' : `Up to ${max} tickets at once.`)
      doing.push('Background jobs pause first: digests, research, sweeps.')
      doing.push('New builds use a cheaper model, or the API credit if it has room.')
      doing.push('In your sessions, helpers use a cheaper model, with one notice.')
      if (step === 'warn') doing.push('Before anything big, your session asks, and offers to queue it or run it on the API credit.')
    }
    if (on && !holds && step !== 'unknown' && reading === 'fresh') {
      if (pace === 'over') doing.push('The week is over pace: queued work slows.')
      if (pace === 'under' && queued > 0) doing.push(`The week is under pace: ${queued} queued ticket${queued === 1 ? '' : 's'} pulled forward.`)
    }

    const guardrails = [
      `The hard line (${LINES.hard}%) holds new work, on or off.`,
      'Running work is never stopped: it finishes.',
      'Fix work passes every line.',
      `GitHub allowance under ${g.gh}% or disk under ${g.disk} GB: no new builds.`,
      'No reading, or an old one: the last known step holds, never 0%.'
    ]

    let flip
    if (holds) flip = `Flipping it changes nothing until ${resetOf || 'the reset'}: the hard line already holds new work.`
    else if (on) flip = `Turn off: new tickets go one at a time per Mac.${n === 1 ? ' The one running now finishes.' : n ? ` The ${n} running now finish.` : ''}`
    else flip = `Turn on: up to ${max} at once, held to the tightest limit${tight ? ` (now: ${tight.label} ${round(tight.pct)}%)` : ''}.`

    let headline
    if (reading === 'stale' && step !== 'unknown') headline = `Last known: ${step === 'clear' ? 'clear' : `${step} line`} · reading ${span(now - recordedAt)} old`
    else if (step === 'unknown') headline = reading === 'none' ? 'No plan reading yet · one at a time per Mac' : 'Plan reading unknown · one at a time per Mac'
    else if (holds) headline = `Holding new work · resets ${resetOf || 'soon'}`
    else if (!on) headline = step === 'clear' ? 'Off · one at a time per Mac' : 'Off · one at a time per Mac, background paused'
    else if (step === 'clear') headline = `Full power · up to ${max} at once`
    else if (step === 'soft') headline = 'Throttled at the soft line · background paused'
    else headline = 'Throttled near the line · asks before big work'

    return { step, reading, five, week, pace, windows, heldBy, newWork, perMac, headline, doing, guardrails, flip }
  }

  root.UsageToggle = { describeThrottle, stepOf, paceOf, windowsSummary, LINES }
})(typeof globalThis !== 'undefined' ? globalThis : window)
