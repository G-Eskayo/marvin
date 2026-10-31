import { accountsSummary, expiryText, STATE_VIEW } from '../lib/accounts_view.js'

// MOCK-UP for Gil's approval (marvin#640): the Vitals Accounts card. Not mounted in any tab yet; the layout and wording
// choices are the Decisions on its PR. Same palette and card shape as the Health tab's CheckCard (HealthDashboard.jsx).
const COLOR = {
  red: { bg: 'bg-red-950', border: 'border-red-900', dot: 'bg-red-500', text: 'text-red-300' },
  yellow: { bg: 'bg-amber-950', border: 'border-amber-900', dot: 'bg-amber-500', text: 'text-amber-300' },
  green: { bg: 'bg-emerald-950', border: 'border-emerald-900', dot: 'bg-emerald-500', text: 'text-emerald-300' },
  unmonitored: { bg: 'bg-neutral-900', border: 'border-neutral-700', dot: 'bg-neutral-600', text: 'text-neutral-400' }
}

function RenewControl({ row, thisMachine, onRenew }) {
  if (row.state === 'works' || row.state === 'not_set_up' || row.state === 'not_needed') return null
  const r = row.renew || {}
  if (r.how === 'tab' && row.machine === thisMachine) {
    return (
      <button onClick={() => onRenew?.(row)} className="shrink-0 rounded-md border border-neutral-600 px-3 py-1 text-xs text-neutral-100 hover:bg-neutral-800">
        Renew…
      </button>
    )
  }
  const cmd = r.command
  return (
    <div className="max-w-[18rem] shrink-0 text-right text-[11px] text-neutral-400">
      <span>Run on {row.machine}:</span>
      <code className="mt-0.5 block rounded bg-neutral-900 px-1.5 py-0.5 font-mono text-neutral-200 [overflow-wrap:anywhere]">{cmd}</code>
    </div>
  )
}

function AccountRow({ row, thisMachine, onRenew, now }) {
  const view = STATE_VIEW[row.state] || STATE_VIEW.unreachable
  const c = COLOR[view.severity] || COLOR.unmonitored
  const exp = expiryText(row, now)
  return (
    <li data-account={row.id} data-state={row.state} className="flex items-start gap-3 px-3 py-2.5">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${c.dot}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium text-white">{row.label}</span>
          <span className={`text-xs ${c.text}`}>{view.word}</span>
          {exp && <span className="text-xs text-neutral-500">· {exp}</span>}
        </div>
        <p className="text-xs text-neutral-400 [overflow-wrap:anywhere]">{String(row.detail || '').split('; runs out ')[0]}</p>
        {(row.state === 'failed' || row.state === 'expiring') && (
          <p className="mt-0.5 text-xs text-neutral-500"><span className="text-neutral-400">Blocks:</span> {row.blocks}</p>
        )}
      </div>
      <RenewControl row={row} thisMachine={thisMachine} onRenew={onRenew} />
    </li>
  )
}

export function AccountsCard({ rows, thisMachine, checkedAt = null, onRenew = null, now = Date.now() }) {
  const s = accountsSummary(rows, { thisMachine })
  const c = COLOR[s.severity] || COLOR.unmonitored
  return (
    <section data-card="accounts" className={`rounded-lg border ${c.border} bg-neutral-950 p-4`}>
      <header className="mb-3 flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${c.dot}`} />
        <h3 className="text-sm font-medium text-white">Accounts</h3>
        <span className={`text-xs ${c.text}`}>{s.headline}</span>
        {checkedAt && <span className="ml-auto text-xs text-neutral-500">checked {checkedAt}</span>}
      </header>
      <div className="flex flex-col gap-3">
        {s.groups.map((g) => (
          <div key={g.machine}>
            <h4 className="mb-1 text-xs uppercase tracking-wide text-neutral-500">{g.machine}{g.machine === thisMachine ? ' (this machine)' : ''}</h4>
            <ul className="divide-y divide-neutral-800 rounded-lg border border-neutral-800">
              {g.rows.map((r) => <AccountRow key={`${r.id}@${r.machine}`} row={r} thisMachine={thisMachine} onRenew={onRenew} now={now} />)}
            </ul>
            {g.hidden > 0 && <p className="mt-1 text-[11px] text-neutral-600">{g.hidden} more not needed on {g.machine}</p>}
          </div>
        ))}
      </div>
    </section>
  )
}
