// Workshop ▸ Projects and Shipped (marvin#864), mock-up logic only, no DOM. Every count, order and line the mock-up
// shows comes from here, and dashboard/test/projects_shipped_proto.test.js tries to break it, so what you see is what
// is tested.
//
// What it reuses, so the build moves code instead of writing a third copy (ADR 0080 rule 2):
//   - from PR #935 (lib/mr_groups.js): the group order (most "your move" first, then size, then name, Other last),
//     the "quiet" collapse rule (a group with nothing for you starts collapsed; your choice wins; empty is always
//     collapsed), the header's "what's yours" line (needsYouSummary) and the tier order inside a group (TIERS).
//     Names come from #935's one lookup (project_names.js nameOf / project_catalog.display_name), as data here.
//   - from Activity (ProjectGoals.jsx, project_progress.js): the goal's first clause, signals as "name —", moving /
//     stuck / held, "N PRs/wk", and "N parked or done" folded at the end.
//   - from MR Review ▸ Merged (MrHistory.jsx, mr_history_view.js): rows grouped by day, newest first, 5 days a page,
//     refused approvals kept, "reverted by #N", merged by you / auto-merge.
// New here: one row per project for tickets *and* PRs (from next_step, as Now), the life track, the lanes line (#1028)
// and the Shipped row's "where it's live" (ADR 0080 I4's ship step).
//
// A classic script, not a module, so the page opens inside MARVIN's sandboxed mock-up window with no build. It sets
// globalThis.ProjectsShipped.
(function (root) {
  'use strict'

  // The life of an item (docs/life-of-a-ticket.md), the same stages as the item page's life strip (#863).
  const STAGES = ['Ticket', 'Look', 'Your answer', 'Build', 'Review', 'Merge', 'Shipped']

  // Now's sections (WorkshopTab.jsx, next_step) and #935's tiers (mr_groups.js TIERS). Words is the `tiers` Decision.
  const NOW_SECTIONS = [
    { id: 'stuck', label: 'Stuck' },
    { id: 'yours', label: 'Your move' },
    { id: 'marvin', label: 'MARVIN is on it' },
    { id: 'next', label: 'Up next' },
    { id: 'waiting', label: 'Waiting on something else' }
  ]
  const TIERS_935 = [
    { id: 'needs-you', label: 'Needs you' },
    { id: 'running', label: 'Checks running' },
    { id: 'waiting', label: 'Waiting on another PR' },
    { id: 'stuck', label: 'Being fixed' },
    { id: 'draft', label: 'Draft' }
  ]
  // A ticket has no #935 tier (#935 is PRs only): where it sits when the screen uses #935's words.
  const TICKET_TIER = { stuck: 'stuck', yours: 'needs-you', marvin: 'running', next: 'waiting', waiting: 'waiting' }

  const OTHER = 'other'
  const REST = new Set(['parked', 'done', 'archived'])
  const PRI = { p1: 0, p2: 1, p3: 2 }

  const list = (x) => (Array.isArray(x) ? x : [])
  const num = (x) => (typeof x === 'number' && Number.isFinite(x) ? x : null)
  const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
  const byName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), undefined, { sensitivity: 'base' })

  // Counts for one project, from its items (each item carries next_step's section).
  function countsOf(project) {
    const items = list(project && project.items)
    const c = { yours: 0, marvin: 0, stuck: 0, next: 0, waiting: 0, total: items.length }
    for (const it of items) if (it && Object.prototype.hasOwnProperty.call(c, it.section) && it.section !== 'total') c[it.section] += 1
    return c
  }

  // Activity's moving / stuck (ProjectGoals.jsx stateOf), with stuck now read from Now's Stuck section as well.
  function stateOf(project) {
    const c = countsOf(project)
    const held = num(project && project.held) || 0
    if (c.stuck > 0) return { text: `stuck ${c.stuck}`, tone: 'red' }
    if (held > 0 && c.yours + c.marvin === 0) return { text: 'held', tone: 'amber' }
    if ((num(project && project.mergedWeek) || 0) > 0 || c.marvin > 0) return { text: 'moving', tone: 'green' }
    return { text: '—', tone: 'dim' }
  }

  // "3 your move · 2 in motion": the ticket's own words for a project row.
  function moveLine(project) {
    const c = countsOf(project)
    const parts = []
    if (c.stuck) parts.push(`${c.stuck} stuck`)
    parts.push(`${c.yours} your move`, `${c.marvin} in motion`)
    if (c.next) parts.push(`${c.next} up next`)
    return parts.join(' · ')
  }

  // #935's needsYouSummary, for tickets and PRs: what your moves are ("1 decision · 2 to approve").
  function yoursLine(project) {
    const mine = list(project && project.items).filter((it) => it && it.section === 'yours')
    if (!mine.length) return 'nothing for you'
    const count = (verbs) => mine.filter((it) => verbs.test(String(it.verb || ''))).length
    const dec = count(/^Answer/)
    const approve = count(/^Approve$/)
    const look = count(/^Approve the look/)
    const info = count(/^Give info/)
    const rest = mine.length - dec - approve - look - info
    return [dec && plural(dec, 'decision'), approve && `${approve} to approve`, look && plural(look, 'look'), info && `${info} to answer`, rest && `${rest} other`]
      .filter(Boolean).join(' · ')
  }

  // #935's order: most for you first, then size, then name; Other last. Parked, done and archived fold away (Activity).
  function orderProjects(projects) {
    const all = list(projects).filter((p) => p && p.id)
    const active = all.filter((p) => !REST.has(p.status) && p.id !== OTHER)
    const other = all.filter((p) => p.id === OTHER && countsOf(p).total > 0)
    const rest = all.filter((p) => REST.has(p.status) && p.id !== OTHER).sort(byName)
    active.sort((a, b) => countsOf(b).yours - countsOf(a).yours || countsOf(b).total - countsOf(a).total || byName(a, b))
    return { active: [...active, ...other], rest }
  }

  // #935's "quiet" rule: nothing for you starts collapsed; your saved choice wins; a project with nothing open is
  // always collapsed.
  function isCollapsed(project, saved = {}) {
    const c = countsOf(project)
    if (!c.total) return true
    if (saved && Object.prototype.hasOwnProperty.call(saved, project.id)) return !!saved[project.id]
    return c.yours + c.stuck === 0
  }

  const rankOf = (it) => [PRI[it.priority] ?? 3, -(num(it.waitingMin) ?? 0), num(it.number) ?? 0]
  const cmp = (a, b) => {
    const x = rankOf(a)
    const y = rankOf(b)
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]
  }

  // An open project's items cut into headings, empty ones left out. words: 'now' (Now's sections) or '935' (#935's tiers).
  function sectionsOf(project, words = 'now') {
    const items = list(project && project.items).filter(Boolean)
    const heads = words === '935' ? TIERS_935 : NOW_SECTIONS
    const keyOf = words === '935'
      ? (it) => (it.isDraft ? 'draft' : it.type === 'pr' && it.tier ? it.tier : TICKET_TIER[it.section] || 'stuck')
      : (it) => (NOW_SECTIONS.some((s) => s.id === it.section) ? it.section : 'waiting')
    return heads
      .map((h) => ({ ...h, items: items.filter((it) => keyOf(it) === h.id).sort(cmp) }))
      .filter((h) => h.items.length)
  }

  // #1028's lanes: one per feature (area:* label or parent ticket); an item with neither lands in Unsorted, never dropped.
  function lanesOf(project) {
    const by = new Map()
    for (const it of list(project && project.items)) {
      if (!it) continue
      const lane = it.lane || 'Unsorted'
      if (!by.has(lane)) by.set(lane, { name: lane, yours: 0, marvin: 0, total: 0 })
      const l = by.get(lane)
      l.total += 1
      if (it.section === 'yours') l.yours += 1
      if (it.section === 'marvin') l.marvin += 1
    }
    const lanes = [...by.values()]
    lanes.sort((a, b) => (a.name === 'Unsorted') - (b.name === 'Unsorted') || b.yours - a.yours || b.total - a.total || byName(a, b))
    return lanes
  }

  // The life track (macro): how many open items sit at each stage, and the tone of the most urgent one there.
  const TONE_RANK = { stuck: 0, yours: 1, marvin: 2, next: 3, waiting: 4 }
  function trackOf(project) {
    const stops = STAGES.map((name) => ({ name, count: 0, tone: null, live: false }))
    for (const it of list(project && project.items)) {
      const s = num(it && it.stage)
      if (s == null || s < 0 || s >= STAGES.length) continue
      const stop = stops[Math.floor(s)]
      stop.count += 1
      if (stop.tone == null || (TONE_RANK[it.section] ?? 9) < (TONE_RANK[stop.tone] ?? 9)) stop.tone = it.section
      // Truthful motion: a stop pulses only when an item there had a real event in the last few minutes.
      if (it.section === 'marvin' && it.liveEvent) stop.live = true
    }
    return stops
  }

  // The item's own life strip: stages before it done, its stage lit in its tone, the rest dark.
  function stripOf(item) {
    const s = Math.max(0, Math.min(STAGES.length - 1, Math.floor(num(item && item.stage) ?? 0)))
    return STAGES.map((_, i) => (i < s ? 'done' : i === s ? (item.section || 'waiting') : 'todo'))
  }

  // Goal, first clause (ProjectGoals shortGoal): up to the first ';' or ',' after 30 characters, else the sentence.
  function shortGoal(goal) {
    const g = String(goal || '').trim()
    if (!g) return ''
    const m = /^(.{30,}?)[;,:]\s/.exec(g)
    const first = m ? m[1] : g.split(/(?<=\.)\s/)[0]
    return first.length > 110 ? `${first.slice(0, 107).trimEnd()}…` : first.replace(/\.$/, '')
  }

  // The line above the projects: "7 active projects · 6 your move · 9 in motion · 1 stuck".
  function lede(groups) {
    const active = list(groups).filter((g) => g && g.id !== OTHER)
    const sum = (k) => list(groups).reduce((n, g) => n + countsOf(g)[k], 0)
    const parts = [plural(active.length, 'active project'), `${sum('yours')} your move`, `${sum('marvin')} in motion`]
    if (sum('stuck')) parts.push(`${sum('stuck')} stuck`)
    return parts.join(' · ')
  }

  // ── Shipped ───────────────────────────────────────────────────────────────────────────────────────────────────

  // Where the work is live (ADR 0080 I4). ship: the project profile's ship step, or null before it has one.
  //   { kind: 'macs', targets: ['MacBook', 'Mini'] }      MARVIN: every Mac pulled and restarted
  //   { kind: 'testflight' }                             Seal Speak: build bumped and uploaded
  //   { kind: 'pages', where: 'gh-pages' }               a site: published
  //   { kind: 'pages', via: 'actions', where: 'marvin.gileskayo.me' }
  //                                                      a site its Actions deploy publishes (marvin#1122): live once
  //                                                      the Pages deployment for the merge succeeded; live.url links it
  // row.live: { state: 'live'|'shipping'|'failed'|'waiting', pulled: [names], build, reason }
  // Only an https link is ever shown as where the work is live (a row's url comes from GitHub's deployment).
  const httpsUrl = (u) => (typeof u === 'string' && /^https:\/\/[^\s"'<>]+$/.test(u) ? u : null)

  function liveLine(row, ship) {
    if (!row || row.kind === 'refused') return null
    if (!ship || !ship.kind) return { text: 'no ship step yet', tone: 'dim', marks: [] }
    const live = row.live || {}
    if (live.state === 'failed') return { text: `ship failed: ${live.reason || 'see the item'}`, tone: 'red', marks: [] }
    if (ship.kind === 'macs') {
      const targets = list(ship.targets)
      const pulled = new Set(list(live.pulled))
      const marks = targets.map((t) => ({ name: t, on: pulled.has(t) }))
      const n = marks.filter((m) => m.on).length
      if (!targets.length) return { text: 'no Macs named in the ship step', tone: 'red', marks }
      if (n === targets.length) return { text: n === 2 ? 'live on both Macs' : `live on all ${n} Macs`, tone: 'green', marks }
      const waiting = marks.filter((m) => !m.on).map((m) => m.name)
      return { text: `live on ${n} of ${targets.length} · ${waiting.join(', ')} pulling`, tone: 'amber', marks }
    }
    if (ship.kind === 'testflight') {
      if (live.state === 'live') return { text: `TestFlight ${live.build || ''}`.trim(), tone: 'green', marks: [{ name: 'TestFlight', on: true }] }
      if (live.state === 'shipping') return { text: 'uploading to TestFlight', tone: 'amber', marks: [{ name: 'TestFlight', on: false }] }
      return { text: 'waits for the next TestFlight build', tone: 'dim', marks: [{ name: 'TestFlight', on: false }] }
    }
    if (ship.kind === 'pages') {
      const where = ship.where || 'the site'
      if (live.state === 'live') return { text: `live on ${where}`, tone: 'green', marks: [{ name: where, on: true }], url: httpsUrl(live.url) }
      if (live.state === 'shipping') {
        const how = ship.via === 'actions' ? 'GitHub Pages deploy running' : `publishing to ${where}`
        return { text: how, tone: 'amber', marks: [{ name: where, on: false }] }
      }
      return { text: `not on ${where} yet`, tone: 'dim', marks: [{ name: where, on: false }] }
    }
    return { text: 'no ship step yet', tone: 'dim', marks: [] }
  }

  const DAY = 86400000
  const dayKey = (ms) => {
    const d = new Date(ms)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }

  // MrHistory's day groups, newest first: "Today", "Yesterday", then "Mon Nov 2". Rows with no readable time go last,
  // under "Time not recorded", never dropped.
  function shippedDays(rows, now) {
    const good = []
    const bad = []
    for (const r of list(rows)) {
      if (!r) continue
      const t = Date.parse(r.at)
      if (Number.isNaN(t)) bad.push(r)
      else good.push({ ...r, t })
    }
    good.sort((a, b) => b.t - a.t)
    const today = dayKey(now)
    const yesterday = dayKey(now - DAY)
    const days = []
    for (const r of good) {
      const key = dayKey(r.t)
      let d = days[days.length - 1]
      if (!d || d.key !== key) {
        const label = key === today ? 'Today' : key === yesterday ? 'Yesterday' : new Date(r.t).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
        d = { key, label, rows: [] }
        days.push(d)
      }
      d.rows.push(r)
    }
    if (bad.length) days.push({ key: 'unknown', label: 'Time not recorded', rows: bad })
    return days
  }

  // 5 days a page, as MR Review ▸ Merged.
  function pageOf(days, page, perPage = 5) {
    const pages = Math.max(1, Math.ceil(list(days).length / perPage))
    const p = Math.max(0, Math.min(pages - 1, Math.floor(num(page) ?? 0)))
    return { page: p, pages, days: list(days).slice(p * perPage, p * perPage + perPage) }
  }

  // The line above Shipped: "this week: 21 merged · 17 live · 1 refused". Live counts only rows whose ship step finished.
  function shippedLede(rows, ships, now) {
    const week = list(rows).filter((r) => r && !Number.isNaN(Date.parse(r.at)) && now - Date.parse(r.at) < 7 * DAY)
    const merged = week.filter((r) => r.kind === 'merged')
    const refused = week.filter((r) => r.kind === 'refused').length
    const live = merged.filter((r) => (liveLine(r, ships && ships[r.project]) || {}).tone === 'green').length
    const withStep = merged.filter((r) => ships && ships[r.project] && ships[r.project].kind).length
    const parts = [`this week: ${merged.length} merged`]
    if (withStep) parts.push(`${live} live`)
    if (refused) parts.push(`${refused} refused`)
    return parts.join(' · ')
  }

  // Ships per day for the last `days` days, oldest first, for the bars above Shipped and in each project's track.
  function perDay(rows, now, days = 14) {
    const out = []
    for (let i = days - 1; i >= 0; i--) out.push({ key: dayKey(now - i * DAY), n: 0 })
    const at = new Map(out.map((d, i) => [d.key, i]))
    for (const r of list(rows)) {
      if (!r || r.kind !== 'merged') continue
      const t = Date.parse(r.at)
      if (Number.isNaN(t)) continue
      const i = at.get(dayKey(t))
      if (i != null) out[i].n += 1
    }
    return out
  }

  root.ProjectsShipped = {
    STAGES, NOW_SECTIONS, TIERS_935, OTHER,
    countsOf, stateOf, moveLine, yoursLine, orderProjects, isCollapsed, sectionsOf, lanesOf, trackOf, stripOf, shortGoal, lede,
    liveLine, shippedDays, pageOf, shippedLede, perDay
  }
})(typeof globalThis !== 'undefined' ? globalThis : window)
