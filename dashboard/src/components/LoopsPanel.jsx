import { useCallback, useEffect, useState } from 'react'
import { STATUS_VIEW, cycleText, fixFor, loopsSummary } from '../lib/loops_view.js'

// Vitals > Loops (marvin#1123, ADR 0083): every MARVIN feedback loop (notice -> act -> verify -> remember), worst
// first, with its status, last full cycle and one fix. Same palette and card shape as Health's CheckCard.
const COLOR = {
  red: { border: 'border-red-900', dot: 'bg-red-500', text: 'text-red-300' },
  yellow: { border: 'border-amber-900', dot: 'bg-amber-500', text: 'text-amber-300' },
  green: { border: 'border-emerald-900', dot: 'bg-emerald-500', text: 'text-emerald-300' },
  unmonitored: { border: 'border-neutral-800', dot: 'bg-neutral-600', text: 'text-neutral-400' }
}
const FILTERS = [['open', 'Needs work'], ['all', 'All']]

function LoopRow({ row, onFix, busy, now }) {
  const v = STATUS_VIEW[row.status]
  const c = COLOR[v.severity]
  const fix = fixFor(row)
  return (
    <li data-loop={row.id} data-status={row.status} className="flex items-start gap-3 px-3 py-2.5">
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${c.dot}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium text-white">{row.name}</span>
          <span className={`text-xs ${c.text}`}>{v.word}</span>
          <span className="text-xs text-neutral-500">· {cycleText(row.last_cycle, now)}</span>
          <span className="text-xs text-neutral-600">· {row.owner === 'gil' ? 'your move' : "MARVIN's move"}</span>
        </div>
        <p className="text-xs text-neutral-400 [overflow-wrap:anywhere]">{String(row.reason || '')}</p>
        {row.ticket && <p className="text-[11px] text-neutral-600">#{row.ticket}</p>}
      </div>
      {fix && (
        <button data-fix={fix.kind} disabled={busy} onClick={() => onFix?.(row)}
          className="shrink-0 rounded-md border border-neutral-600 px-3 py-1 text-xs text-neutral-100 hover:bg-neutral-800 disabled:opacity-50">
          {busy ? 'Working…' : fix.label}
        </button>
      )}
    </li>
  )
}

export function LoopsView({ view, onFix = null, busyId = null, note = null, now = Date.now(), filter = 'open', onFilter = null }) {
  const s = loopsSummary(view)
  const c = COLOR[s.severity]
  const rows = filter === 'all' ? s.rows : s.rows.filter((r) => r.status !== 'closed')
  return (
    <section data-testid="loops-panel" className={`rounded-lg border ${c.border} bg-neutral-950 p-4`}>
      <header className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className={`h-2.5 w-2.5 rounded-full ${c.dot}`} />
        <h3 className="text-sm font-semibold text-white">Loops</h3>
        <span className="text-sm text-neutral-300">{s.verdict}</span>
        <span className="text-xs text-neutral-500">
          {s.counts.closed} closed · {s.counts.stalled} stalled · {s.counts.broken} broken · {s.counts.not_wired} not wired
        </span>
        <div className="ml-auto flex gap-1">
          {FILTERS.map(([id, label]) => (
            <button key={id} onClick={() => onFilter?.(id)}
              className={`rounded px-2 py-0.5 text-xs ${filter === id ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}>{label}</button>
          ))}
        </div>
      </header>
      <p className="mb-2 text-xs text-neutral-500">A loop works when all four steps run: notice, act, verify, remember.</p>
      {(note || view?.problem) && <p className="mb-2 text-xs text-neutral-400 [overflow-wrap:anywhere]">{note || `Couldn't read the loops: ${view.problem}`}</p>}
      <ul className="divide-y divide-neutral-900">
        {rows.map((r) => <LoopRow key={r.id} row={r} onFix={onFix} busy={busyId === r.id} now={now} />)}
      </ul>
      {view?.problems?.length > 0 && (
        <p className="mt-2 text-xs text-amber-400">{view.problems.length} registry entr{view.problems.length === 1 ? 'y' : 'ies'} couldn't be read: {view.problems.map((p) => p.loop || '?').join(', ')}</p>
      )}
    </section>
  )
}

export default function LoopsPanel({ api = typeof window !== 'undefined' ? window.api?.loops : null, onOpenTicket = null }) {
  const [view, setView] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [note, setNote] = useState(null)
  const [filter, setFilter] = useState('open')
  const load = useCallback(async () => {
    if (!api?.status) return
    try { setView(await api.status()) } catch (err) { setNote(String(err?.message || err).slice(0, 160)) }
  }, [api])
  useEffect(() => { load() }, [load])
  if (!api?.status) return null
  if (!view) return <p data-testid="loops-loading" className="text-xs text-neutral-500">Reading the loops…</p>
  const onFix = async (row) => {
    setBusyId(row.id)
    try {
      const r = await api.fix(row.id)
      if (r?.ok && r.how === 'open' && r.repo && r.number && onOpenTicket) onOpenTicket(r.repo, r.number)
      setNote(r?.ok ? `${row.name}: ${r.says || 'done'}` : `${row.name}: ${r?.error || 'the fix failed'}`)
    } catch (err) {
      setNote(String(err?.message || err).slice(0, 160))
    } finally {
      setBusyId(null)
      load()
    }
  }
  return <LoopsView view={view} onFix={onFix} busyId={busyId} note={note} filter={filter} onFilter={setFilter} />
}
