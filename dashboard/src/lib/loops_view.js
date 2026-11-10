// Vitals > Loops (marvin#1123, ADR 0083): how each loop row reads. Pure, O(loops).

export const STATUS_VIEW = {
  broken: { word: 'Broken', severity: 'red' },
  stalled: { word: 'Stalled', severity: 'yellow' },
  not_wired: { word: 'Not wired', severity: 'unmonitored' },
  closed: { word: 'Closed', severity: 'green' }
}
export const FIX_LABEL = {
  rerun: 'Re-run',
  relogin: 'Re-login',
  install_job: 'Install job',
  rollback: 'Roll back',
  ticket: 'File ticket',
  decision: 'Answer Decision'
}
const ORDER = ['broken', 'stalled', 'not_wired', 'closed']

export function cycleText(iso, now = Date.now()) {
  const t = Date.parse(iso || '')
  if (!Number.isFinite(t)) return 'no full cycle seen'
  const h = Math.max(0, Math.round((now - t) / 3_600_000))
  return `last full cycle ${h < 1 ? 'under an hour ago' : h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`}`
}

// The fix button shows for every loop that isn't closed. A loop whose fix is a ticket and that already has one says so.
export function fixFor(row) {
  if (!row || row.status === 'closed') return null
  const kind = row.fix?.kind
  return FIX_LABEL[kind] ? { kind, label: FIX_LABEL[kind], level: row.fix.level } : null
}

export function loopsSummary(view) {
  const rows = (Array.isArray(view?.loops) ? view.loops : []).filter((r) => r && typeof r.id === 'string' && STATUS_VIEW[r.status])
  rows.sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || String(a.name).localeCompare(String(b.name)))
  const count = (s) => rows.filter((r) => r.status === s).length
  const verdict = count('broken') ? `${count('broken')} broken` : count('stalled') ? `${count('stalled')} stalled` : rows.length ? 'Every wired loop closes' : 'No loops yet'
  return {
    rows,
    counts: Object.fromEntries(ORDER.map((s) => [s, count(s)])),
    verdict,
    severity: count('broken') ? 'red' : count('stalled') ? 'yellow' : 'green'
  }
}
