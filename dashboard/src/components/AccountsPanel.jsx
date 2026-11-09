import { useCallback, useEffect, useState } from 'react'
import { AccountsCard } from './AccountsCard.jsx'

// Vitals > Accounts at the top of Health (marvin#977/#640, Gil's answer: "A: its own card at the top of Health,
// always visible"). Loads the saved view at once, then this machine checked fresh; Renew opens the account's own tab.
export default function AccountsPanel({ api = typeof window !== 'undefined' ? window.api?.accounts : null }) {
  const [view, setView] = useState(null)
  const [note, setNote] = useState(null)
  const load = useCallback(async (fresh) => {
    if (!api?.list) return
    try { setView(await api.list({ fresh })) } catch (err) { setNote(String(err?.message || err).slice(0, 160)) }
  }, [api])
  useEffect(() => { load(false).then(() => load(true)) }, [load])
  if (!api?.list) return null
  if (!view) return <p data-testid="accounts-loading" className="mb-4 text-xs text-neutral-500">Checking accounts…</p>
  const onRenew = async (row) => {
    try {
      const r = await api.renew(row.id, row.machine)
      setNote(r?.started ? `Renewing ${r.title} in its own tab` : r?.command ? `Run on ${r.where}: ${r.command}` : null)
    } catch (err) { setNote(String(err?.message || err).slice(0, 160)) }
  }
  return (
    <div data-testid="accounts-panel" className="mb-6">
      <AccountsCard rows={view.accounts || []} thisMachine={view.thisMachine || null} checkedAt={view.generatedAt} onRenew={onRenew} />
      {(note || view.freshProblem) && <p className="mt-1 text-xs text-neutral-500">{note || `This Mac couldn't be checked just now: ${view.freshProblem}`}</p>}
    </div>
  )
}
