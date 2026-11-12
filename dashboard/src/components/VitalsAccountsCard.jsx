import { accountsBoard, expiryText, STATE_VIEW } from '../lib/accounts_view.js'

// Vitals ▸ Accounts (marvin#873; owner 2026-11-11: "redesigned here, once, as a Vitals card"; Health's AccountsCard is
// frozen). One panel per Mac side by side, so the card's width carries the machines instead of one long list; a
// working account is one line with its time left, and only a problem opens up with what it blocks and its renewal.
// #974's answers: grouped by machine, "not needed here" folded into a count, gh's own login shown but never alerting,
// amber 14 days before expiry. Under 900 px the Mac panels stack.

const MARK = { failed: 'failure', expiring: 'missed', unreachable: 'unknown', works: 'ok', not_set_up: 'unknown' }

function DaysLeft({ row }) {
  if (row.daysLeft == null) return <span className="v-dim">{row.state === 'works' ? 'no expiry' : ''}</span>
  if (row.daysLeft < 0) return <span className="v-red">expired</span>
  const soon = row.daysLeft <= 14
  return (
    <span className="whitespace-nowrap" title={expiryText(row)}>
      <span className={`v-days ${soon ? 'soon' : ''}`} aria-hidden="true"><i style={{ width: `${Math.max(4, Math.min(100, (row.daysLeft / 365) * 100))}%` }} /></span>
      <span className={soon ? 'v-amber' : 'v-dim'}> {row.estimated ? '~' : ''}{row.daysLeft} d</span>
    </span>
  )
}

function Renew({ row, thisMachine, onRenew }) {
  const r = row.renew || {}
  if (r.how === 'tab' && row.machine === thisMachine && onRenew) {
    return <button type="button" className="v-btn" onClick={() => onRenew(row)}>One tap: Renew…</button>
  }
  if (!r.command) return null
  return (
    <span className="block">
      <span className="v-dim">Run on {row.machine}: </span>
      <code className="text-[12px] text-white [overflow-wrap:anywhere]">{r.command}</code>
    </span>
  )
}

function AccountLine({ row, thisMachine, onRenew }) {
  const view = STATE_VIEW[row.state] || STATE_VIEW.unreachable
  const problem = row.state === 'failed' || row.state === 'expiring' || row.state === 'unreachable'
  const mark = MARK[row.state] || 'unknown'
  const tone = row.quiet ? 'v-dim' : view.severity === 'red' ? 'v-red' : view.severity === 'yellow' ? 'v-amber' : view.severity === 'green' ? 'v-green' : ''
  return (
    <div data-account={row.id} data-state={row.state} data-quiet={row.quiet ? '1' : undefined} className="v-acct-row">
      <span className={`v-mark ${mark}`} style={row.quiet && problem ? { opacity: 0.6 } : undefined} aria-hidden="true" />
      <span className="min-w-0">
        <span className="text-white">{row.label}</span>
        {problem && <span className={`ml-2 ${tone}`}>{view.word}{row.quiet ? ' · not alerting' : ''}</span>}
        {problem && (
          <span className="mt-0.5 block text-[12px]">
            <span className="v-dim [overflow-wrap:anywhere]">{String(row.detail || '').split('; runs out ')[0]}</span>
            {!row.quiet && row.blocks && <span className="block"><span className="v-dim">Blocks: </span>{row.blocks}</span>}
            {!row.quiet && <Renew row={row} thisMachine={thisMachine} onRenew={onRenew} />}
          </span>
        )}
      </span>
      <span className="text-right text-[12px]">{problem ? null : <DaysLeft row={row} />}</span>
    </div>
  )
}

export function VitalsAccountsCard({ rows, thisMachine = null, checkedAge = null, onRenew = null, now = Date.now() }) {
  const b = accountsBoard(rows, { thisMachine, now })
  const tone = b.severity === 'red' ? 'v-red' : b.severity === 'yellow' ? 'v-amber' : 'v-green'
  const hidden = b.groups.reduce((n, g) => n + g.hidden, 0)
  return (
    <section data-card="vitals-accounts" className="v-panel p-4">
      <header className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h3 className="v-display text-[17px] text-white">Accounts</h3>
        <span className={`v-display text-[15px] ${tone}`}>{b.headline}</span>
        <span className="v-dim">
          {b.counts.shown} on {b.counts.machines} Mac{b.counts.machines === 1 ? '' : 's'}{hidden ? ` · ${hidden} not needed` : ''}{b.quiet ? ` · ${b.quiet} not alerting` : ''}
        </span>
        {checkedAge && <span className="v-dim ml-auto">checked {checkedAge}</span>}
      </header>
      {b.groups.length === 0 ? (
        <p className="v-dim">No accounts read yet. The Mac mini's sweep writes them every 15 minutes.</p>
      ) : (
        <div className="v-acct-grid">
          {b.groups.map((g) => (
            <div key={g.machine} className="v-acct-mac" data-machine={g.machine}>
              <h4 className="v-display mb-1 text-[13px] v-amber">{g.machine}{g.here ? ' · this Mac' : ''}</h4>
              {g.rows.map((r) => <AccountLine key={`${r.id}@${r.machine}`} row={r} thisMachine={thisMachine} onRenew={onRenew} />)}
              {g.hidden > 0 && <p className="v-dim mt-1 text-[12px]">{g.hidden} not needed here</p>}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
