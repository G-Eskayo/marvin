// Pure helpers behind the Metrics tab's Tools and Usage views: merge what each machine scanned, pick a machine, build the series.

const KINDS = ['interactive', 'headless', 'subagent']
const pick = (machines, which) => machines.filter((m) => which === 'all' || m.machine === which)

const addCounts = (a, b) => {
  const out = { ...a }
  for (const [k, v] of Object.entries(b || {})) out[k] = (out[k] || 0) + v
  return out
}

// Rows of one kind ('tools', 'skills', 'mcp_servers', 'agents') from the chosen machines, the same name added together.
export function mergeRows(machines, which = 'all', listKey = 'tools', nameKey = 'name') {
  const byName = new Map()
  for (const m of pick(machines, which)) {
    for (const t of m.tools?.[listKey] || []) {
      const cur = byName.get(t[nameKey])
      if (!cur) {
        byName.set(t[nameKey], { ...t, by_kind: { ...t.by_kind }, by_day: { ...t.by_day }, via: { ...(t.via || {}) }, causes: { ...(t.causes || {}) } })
        continue
      }
      for (const f of ['calls', 'ok', 'error', 'rejected', 'interrupted', 'invalid', 'unresolved', 'expected']) cur[f] += t[f]
      cur.by_kind = addCounts(cur.by_kind, t.by_kind)
      cur.by_day = addCounts(cur.by_day, t.by_day)
      cur.via = addCounts(cur.via, t.via)
      cur.causes = addCounts(cur.causes, t.causes)
      if (t.last_used && (!cur.last_used || t.last_used > cur.last_used)) cur.last_used = t.last_used
      if (t.purpose && !cur.purpose) cur.purpose = t.purpose
    }
  }
  return [...byName.values()].sort((a, b) => b.calls - a.calls || String(a[nameKey]).localeCompare(String(b[nameKey])))
}

export const mergeTools = (machines, which = 'all') => mergeRows(machines, which, 'tools')

// Our skills that never fired: a skill counts as used if ANY chosen machine used it, so the never-used list is the names
// every chosen machine lists as unused.
export function mergeInventory(machines, which = 'all') {
  const scans = pick(machines, which).map((m) => m.tools?.inventory).filter(Boolean)
  if (scans.length === 0) return { known: 0, used: 0, never_used: [] }
  const never = scans.map((i) => i.never_used).reduce((acc, list) => acc.filter((n) => list.includes(n)))
  const known = Math.max(...scans.map((i) => i.known))
  return { known, used: known - never.length, never_used: never }
}

export function mergeFailures(machines, which = 'all', limit = 40) {
  return pick(machines, which)
    .flatMap((m) => (m.tools?.recent_failures || []).map((f) => ({ ...f, machine: m.machine })))
    .sort((a, b) => (a.at < b.at ? 1 : -1))
    .slice(0, limit)
}

export const mergeTokenRows = (machines, which = 'all') => pick(machines, which).flatMap((m) => m.tokens?.rows || [])

const valueOf = (r, metric) => (metric === 'all' ? r.input + r.output + r.cache_write + r.cache_read : r.output)

function dayList(days, end) {
  const last = new Date(`${end}T00:00:00Z`)
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(last)
    d.setUTCDate(d.getUTCDate() - (days - 1 - i))
    return d.toISOString().slice(0, 10)
  })
}

export function dailySeries(rows, { days = 30, end, metric = 'output' } = {}) {
  const list = dayList(days, end || new Date().toISOString().slice(0, 10))
  const idx = new Map(list.map((d, i) => [d, { day: d, interactive: 0, headless: 0, subagent: 0, total: 0 }]))
  for (const r of rows) {
    const cell = idx.get(r.day)
    if (!cell) continue
    const v = valueOf(r, metric)
    cell[r.kind] = (cell[r.kind] || 0) + v
    cell.total += v
  }
  return list.map((d) => idx.get(d))
}

export function sumRows(rows, { days = 30, end } = {}) {
  const wanted = new Set(dayList(days, end || new Date().toISOString().slice(0, 10)))
  const out = { input: 0, output: 0, cache_write: 0, cache_read: 0, messages: 0, byKind: { interactive: 0, headless: 0, subagent: 0 } }
  for (const r of rows) {
    if (!wanted.has(r.day)) continue
    for (const f of ['input', 'output', 'cache_write', 'cache_read', 'messages']) out[f] += r[f]
    out.byKind[r.kind] = (out.byKind[r.kind] || 0) + r.output
  }
  return out
}

export function projectTable(machines, which = 'all') {
  const byProject = new Map()
  for (const m of pick(machines, which)) {
    for (const p of m.tokens?.by_project || []) {
      const cur = byProject.get(p.project) || { project: p.project, input: 0, output: 0, cache_write: 0, cache_read: 0, messages: 0, by_kind: {} }
      for (const f of ['input', 'output', 'cache_write', 'cache_read', 'messages']) cur[f] += p[f]
      cur.by_kind = addCounts(cur.by_kind, p.by_kind)
      byProject.set(p.project, cur)
    }
  }
  return [...byProject.values()].sort((a, b) => b.output - a.output)
}

export function ticketTable(machines, which = 'all') {
  const byKey = new Map()
  for (const m of pick(machines, which)) {
    for (const t of m.tokens?.by_ticket || []) {
      const key = `${t.project}#${t.ticket}`
      const cur = byKey.get(key) || { project: t.project, ticket: t.ticket, input: 0, output: 0, cache_write: 0, cache_read: 0, messages: 0 }
      for (const f of ['input', 'output', 'cache_write', 'cache_read', 'messages']) cur[f] += t[f]
      byKey.set(key, cur)
    }
  }
  return [...byKey.values()].sort((a, b) => b.output - a.output)
}

const agoText = (ms) => {
  const min = Math.max(1, Math.round(ms / 60000))
  if (min < 60) return `${min} min ago`
  const h = Math.round(min / 60)
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} d ago`
}

export function machineFreshness(m, now = Date.now()) {
  if (!m.reachable) return { state: 'unreachable', text: 'not reachable right now' }
  const stamps = [m.tools?.generated_at, m.tokens?.generated_at].filter(Boolean).map(Date.parse).filter(Number.isFinite)
  if (stamps.length === 0) return { state: 'no-data', text: 'no scan yet' }
  return { state: 'ok', text: `updated ${agoText(now - Math.max(...stamps))}` }
}

export function autonomousSeries(rows, { days = 30, end } = {}) {
  const list = dayList(days, end || new Date().toISOString().slice(0, 10))
  const idx = new Map(list.map((d) => [d, { day: d, autonomous: 0, interactive: 0, total: 0 }]))
  for (const r of rows) {
    const cell = idx.get(r.day)
    if (!cell) continue
    const v = r.output || 0
    if (r.kind === 'headless' || r.kind === 'subagent') {
      cell.autonomous += v
      cell.total += v
    } else if (r.kind === 'interactive') {
      cell.interactive += v
      cell.total += v
    }
  }
  return list.map((d) => {
    const c = idx.get(d)
    return { day: d, autonomous: c.autonomous, interactive: c.interactive, total: c.total, share: c.total > 0 ? Math.round(100 * c.autonomous / c.total) : 0 }
  })
}

export function weeklySeries(rows, { end } = {}) {
  const endDate = new Date((end || new Date().toISOString().slice(0, 10)) + 'T00:00:00Z')
  const weeks = new Map()
  for (let i = 0; i < 12; i++) {
    const d = new Date(endDate)
    d.setUTCDate(d.getUTCDate() - (7 * (11 - i)))
    const weekStart = new Date(d)
    weekStart.setUTCDate(weekStart.getUTCDate() - weekStart.getUTCDay())
    const week = weekStart.toISOString().slice(0, 10)
    weeks.set(week, { week, autonomous: 0, interactive: 0, total: 0 })
  }
  for (const r of rows) {
    const d = new Date(r.day + 'T00:00:00Z')
    const weekStart = new Date(d)
    weekStart.setUTCDate(weekStart.getUTCDate() - weekStart.getUTCDay())
    const week = weekStart.toISOString().slice(0, 10)
    const w = weeks.get(week)
    if (w) {
      const v = r.output || 0
      if (r.kind === 'headless' || r.kind === 'subagent') {
        w.autonomous += v
        w.total += v
      } else if (r.kind === 'interactive') {
        w.interactive += v
        w.total += v
      }
    }
  }
  return [...weeks.values()].map(w => ({ ...w, share: w.total > 0 ? Math.round(100 * w.autonomous / w.total) : 0 })).sort((a, b) => a.week.localeCompare(b.week))
}

export function jobTable(machines, which = 'all') {
  const byTicket = new Map()
  for (const m of pick(machines, which)) {
    for (const j of m.tokens?.by_job || []) {
      const ticket = j.ticket
      const cur = byTicket.get(ticket) || { ticket, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, runs: 0 }
      cur.input_tokens += j.input_tokens || 0
      cur.output_tokens += j.output_tokens || 0
      cur.cache_read_tokens += j.cache_read_tokens || 0
      cur.cache_write_tokens += j.cache_write_tokens || 0
      cur.runs += j.runs || 0
      byTicket.set(ticket, cur)
    }
  }
  const list = [...byTicket.values()]
  const total = list.reduce((sum, j) => sum + (j.output_tokens || 0), 0)
  return list.map((j) => ({
    ticket: j.ticket,
    output_tokens: j.output_tokens || 0,
    share_pct: total > 0 ? Math.round(100 * (j.output_tokens || 0) / total) : 0,
  })).sort((a, b) => b.output_tokens - a.output_tokens)
}

export const USAGE_KINDS = KINDS
