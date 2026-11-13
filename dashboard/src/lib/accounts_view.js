// Vitals > Accounts (marvin#974; card design awaiting Gil's approval in #640): the rows from lib/accounts.py, as the
// card shows them. Pure, O(rows).

// state -> the Health palette's severity (HealthDashboard.jsx SEVERITY_COLOR) and the words on the row.
export const STATE_VIEW = {
  failed: { severity: 'red', word: 'Needs renewing' },
  expiring: { severity: 'yellow', word: 'Runs out soon' },
  unreachable: { severity: 'unmonitored', word: "Couldn't check" },
  works: { severity: 'green', word: 'Works' },
  not_set_up: { severity: 'unmonitored', word: 'Not set up' },
  not_needed: { severity: 'unmonitored', word: 'Not needed here' }
}
const ORDER = ['failed', 'expiring', 'unreachable', 'works', 'not_set_up', 'not_needed']

export function daysLeft(expiresAt, now = Date.now()) {
  const t = Date.parse(expiresAt || '')
  return Number.isFinite(t) ? Math.floor((t - now) / 86_400_000) : null
}

export function expiryText(row, now = Date.now()) {
  const d = daysLeft(row?.expires_at, now)
  if (d == null) return row?.state === 'works' ? 'no expiry date' : ''
  const date = String(row.expires_at).slice(0, 10)
  const about = row.estimated ? 'about ' : ''
  if (d < 0) return `expired ${about}${date}`
  return `${d === 0 ? 'today' : `${d} day${d === 1 ? '' : 's'}`} left (${about}${date})`
}

// The card: machines in a fixed order (this one first), rows worst-first; "not needed" rows folded into a count.
export function accountsSummary(rows = [], { thisMachine = null } = {}) {
  const machines = new Map()
  for (const r of Array.isArray(rows) ? rows : []) {
    if (!r || typeof r.id !== 'string') continue
    const m = r.machine || 'unknown'
    if (!machines.has(m)) machines.set(m, [])
    machines.get(m).push(r)
  }
  const groups = [...machines.entries()].map(([machine, list]) => {
    const shown = list.filter((r) => r.state !== 'not_needed').sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state))
    return { machine, rows: shown, hidden: list.length - shown.length, worst: shown[0]?.state || 'works' }
  })
  groups.sort((a, b) => (a.machine === thisMachine ? -1 : b.machine === thisMachine ? 1 : ORDER.indexOf(a.worst) - ORDER.indexOf(b.worst) || a.machine.localeCompare(b.machine)))
  const all = groups.flatMap((g) => g.rows)
  const count = (s) => all.filter((r) => r.state === s).length
  const worst = all.map((r) => r.state).sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))[0] || 'works'
  const headline = count('failed')
    ? `${count('failed')} need${count('failed') === 1 ? 's' : ''} renewing`
    : count('expiring') ? `${count('expiring')} run${count('expiring') === 1 ? 's' : ''} out soon` : 'All signed in'
  return { groups, worst, severity: STATE_VIEW[worst]?.severity || 'unmonitored', headline }
}

// The Vitals Accounts card (marvin#873; owner 2026-11-11: redesigned once, here, as a Vitals card; Health's card above
// is frozen). #974's answers kept: every account on every machine grouped by machine, "not needed here" folded into a
// count, gh's own login (alert: false in lib/accounts.py) shown but never alerting, amber 14 days before expiry.
export const AMBER_DAYS = 14

export function accountsBoard(rows = [], { thisMachine = null, now = Date.now() } = {}) {
  const machines = new Map()
  for (const r of Array.isArray(rows) ? rows : []) {
    if (!r || typeof r.id !== 'string') continue
    const m = r.machine || 'unknown'
    if (!machines.has(m)) machines.set(m, [])
    const left = daysLeft(r.expires_at, now)
    const state = r.state === 'works' && left != null && left <= AMBER_DAYS ? 'expiring' : r.state
    machines.get(m).push({ ...r, state, daysLeft: left, quiet: r.alert === false })
  }
  const alerting = (x) => !x.quiet
  const groups = [...machines.entries()].map(([machine, list]) => {
    const shown = list.filter((x) => x.state !== 'not_needed').sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || a.id.localeCompare(b.id))
    const worst = shown.filter(alerting).map((x) => x.state).sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))[0] || 'works'
    return { machine, rows: shown, hidden: list.length - shown.length, worst, here: machine === thisMachine }
  })
  groups.sort((a, b) => (a.here ? -1 : b.here ? 1 : ORDER.indexOf(a.worst) - ORDER.indexOf(b.worst) || a.machine.localeCompare(b.machine)))
  const shown = groups.flatMap((g) => g.rows)
  const loud = shown.filter(alerting)
  const count = (s) => loud.filter((x) => x.state === s).length
  const failed = count('failed')
  const expiring = count('expiring')
  const worst = loud.map((x) => x.state).sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))[0] || 'works'
  const headline = failed ? `${failed} need${failed === 1 ? 's' : ''} renewing` : expiring ? `${expiring} run${expiring === 1 ? 's' : ''} out soon` : 'All signed in'
  return { groups, headline, worst, severity: STATE_VIEW[worst]?.severity || 'unmonitored', quiet: shown.filter((x) => x.quiet && x.state !== 'works').length,
    counts: { shown: shown.length, failed, expiring, machines: groups.length } }
}
