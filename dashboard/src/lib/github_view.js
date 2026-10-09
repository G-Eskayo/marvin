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
