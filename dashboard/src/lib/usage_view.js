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
        byName.set(t[nameKey], { ...t, by_kind: { ...t.by_kind }, by_day: { ...t.by_day }, via: { ...(t.via || {}) } })
        continue
      }
      for (const f of ['calls', 'ok', 'error', 'rejected', 'interrupted', 'invalid', 'unresolved']) cur[f] += t[f]
      cur.by_kind = addCounts(cur.by_kind, t.by_kind)
      cur.by_day = addCounts(cur.by_day, t.by_day)
      cur.via = addCounts(cur.via, t.via)
      if (t.last_used && (!cur.last_used || t.last_used > cur.last_used)) cur.last_used = t.last_used
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

export const USAGE_KINDS = KINDS
