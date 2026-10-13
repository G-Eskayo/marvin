// The Metrics tab's GitHub section: combine each Mac's summary (lib/github_usage.py, via usage_report.py) into one view.
export const GROUPS = ['dashboard', 'pipeline', 'tests', 'health', 'people', 'other']

const pick = (machines, which) => (machines || []).filter((m) => m.github && (which === 'all' || m.machine === which))

export function mergeHours(machines, which) {
  const byHour = new Map()
  for (const m of pick(machines, which)) {
    for (const h of m.github.hours || []) {
      const o = byHour.get(h.hour) || { hour: h.hour, total: 0, refused: 0, deferred: 0, groups: Object.fromEntries(GROUPS.map((g) => [g, 0])) }
      o.total += h.total || 0
      o.refused += h.refused || 0
      o.deferred += h.deferred || 0
      for (const g of GROUPS) o.groups[g] += h.groups?.[g] || 0
      byHour.set(h.hour, o)
    }
  }
  return [...byHour.values()].sort((a, b) => (a.hour < b.hour ? -1 : 1))
}

// GitHub's allowance is one per account, so every Mac's readings belong on one timeline.
export function mergeBudget(machines) {
  return (machines || []).flatMap((m) => m.github?.budget || []).filter((b) => b.graphql != null).sort((a, b) => a.at - b.at)
}

export function mergeTop(machines, which, limit = 10) {
  return pick(machines, which)
    .flatMap((m) => (m.github.top || []).map((t) => ({ ...t, machine: m.machine })))
    .sort((a, b) => b.calls - a.calls)
    .slice(0, limit)
}

export function lastHourTotals(machines, which) {
  const hours = mergeHours(machines, which)
  const last = hours[hours.length - 1]
  return last ? { total: last.total, refused: last.refused, deferred: last.deferred } : { total: 0, refused: 0, deferred: 0 }
}

// ── marvin#417: hourly low-point bars linked to calls per hour ─────────────
// GitHub refills the allowance every hour, so raw readings drew a sawtooth. Each slot now carries that hour's LOWEST
// allowance (both Macs: it is one account-wide allowance) next to its calls, so "how close did we get, and who spent it"
// reads off one column.
export const RANGES = { '24h': { hours: 24, slotHours: 1 }, '7d': { hours: 168, slotHours: 1 }, '30d': { hours: 720, slotHours: 6 } }
const GROUP_LABEL = { dashboard: 'Dashboard', pipeline: 'Pipeline', tests: 'Tests', health: 'Health checks', people: 'You', other: 'Other' }
const RANGE_KEY = 'metrics.github.range'

const minOf = (a, b) => (a == null ? b : b == null ? a : Math.min(a, b))

function addCallers(into, callers) {
  for (const c of callers || []) into.set(c.caller, { ...c, calls: (into.get(c.caller)?.calls || 0) + (c.calls || 0) })
}

function emptySlot(key) {
  return { key, total: 0, refused: 0, deferred: 0, groups: Object.fromEntries(GROUPS.map((g) => [g, 0])), budgetMin: null, readings: 0, _callers: new Map() }
}

function addHour(slot, h, { calls = true, budget = true } = {}) {
  if (calls) {
    slot.total += h.total || 0
    slot.refused += h.refused || 0
    slot.deferred += h.deferred || 0
    for (const g of GROUPS) slot.groups[g] += h.groups?.[g] || 0
    addCallers(slot._callers, h.callers)
  }
  if (budget && typeof h.budget_min === 'number') {
    slot.budgetMin = minOf(slot.budgetMin, h.budget_min)
    slot.readings += h.budget_readings || 1
  }
}

function finish(slot) {
  const { _callers, ...rest } = slot
  return { ...rest, callers: [..._callers.values()].sort((a, b) => b.calls - a.calls).slice(0, 5) }
}

export function timeline(machines, which, range) {
  const r = RANGES[range] ? range : '24h'
  const { hours, slotHours } = RANGES[r]
  const byHour = new Map()
  for (const m of (machines || []).filter((x) => x.github)) {
    const mine = which === 'all' || m.machine === which
    for (const h of m.github.hours || []) {
      if (!h || !h.hour) continue
      const s = byHour.get(h.hour) || emptySlot(h.hour)
      addHour(s, h, { calls: mine, budget: true }) // the allowance belongs to the account, whichever Mac is picked
      byHour.set(h.hour, s)
    }
  }
  const all = [...byHour.values()].sort((a, b) => (a.key < b.key ? -1 : 1)).slice(-hours).map(finish)
  if (slotHours === 1) return { range: r, slotHours, slots: all.map((s) => ({ ...s, label: labelOf(s.key, 1, r), span: spanOf(s.key) })) }
  const slots = []
  for (let i = 0; i < all.length; i += slotHours) {
    const group = all.slice(i, i + slotHours)
    const s = emptySlot(group[0].key)
    for (const g of group) {
      addHour(s, { ...g, budget_min: g.budgetMin, budget_readings: g.readings, callers: g.callers })
    }
    slots.push({ ...finish(s), label: labelOf(group[0].key, slotHours, r), span: spanOf(group[0].key, slotHours) })
  }
  return { range: r, slotHours, slots }
}

function parseKey(key) {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}):00Z$/.exec(key || '')
  return m ? new Date(`${m[1]}T${m[2]}:00:00Z`) : null
}

const timeOf = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
const dateOf = (d) => d.toLocaleDateString([], { month: 'short', day: 'numeric' })

// Axis label: the hour for 24 h / 7 d (with the date at 7 d), just the date for 30 d.
function labelOf(key, slotHours = 1, range = '24h') {
  const d = parseKey(key)
  if (!d) return key || ''
  if (slotHours > 1) return dateOf(d)
  return range === '7d' ? `${dateOf(d)} ${timeOf(d)}` : timeOf(d)
}

// Detail label: the full span a bar covers.
function spanOf(key, slotHours = 1) {
  const d = parseKey(key)
  if (!d) return key || ''
  if (slotHours === 1) return `${dateOf(d)}, ${timeOf(d)}`
  return `${dateOf(d)}, ${timeOf(d)}–${timeOf(new Date(d.getTime() + slotHours * 3600_000))}`
}

// Same thresholds as the "allowance left" tile and the gate's 20% floor.
export function allowanceTone(v) {
  if (v == null) return 'none'
  if (v <= 0) return 'out'
  if (v < 0.2) return 'red'
  if (v < 0.5) return 'amber'
  return 'green'
}

export function slotDetail(s) {
  const low = s.budgetMin == null ? 'no allowance reading' : s.budgetMin <= 0 ? 'ran out' : `low ${Math.round(s.budgetMin * 100)}%`
  return {
    headline: `${s.span || s.label} · ${low} · ${(s.total || 0).toLocaleString('en-US')} calls`,
    split: GROUPS.filter((g) => s.groups?.[g]).sort((a, b) => s.groups[b] - s.groups[a]).map((g) => `${GROUP_LABEL[g]} ${s.groups[g].toLocaleString('en-US')}`),
    callers: (s.callers || []).map((c) => `${c.caller} ${(c.calls || 0).toLocaleString('en-US')}`),
    refused: s.refused || 0,
    deferred: s.deferred || 0
  }
}

export function readRange(storage) {
  try {
    const v = storage?.getItem(RANGE_KEY)
    return RANGES[v] ? v : '24h'
  } catch {
    return '24h'
  }
}

export function writeRange(storage, range) {
  try {
    storage?.setItem(RANGE_KEY, range)
  } catch {
    // private window or full storage: the choice just isn't remembered
  }
}
