import { useCallback, useEffect, useState } from 'react'
import { useScrollArea } from './ScrollPlaces.jsx'
import { SNOOZE_OPTIONS, defaultBackup, doneMessage, prettyDate, untilArgs } from '../lib/proposals_view.js'

// MR Review → Proposals (#102, ADR 0068): big north-star ideas, written for a lay reader, each one actionable.
// Everything goes through window.api.proposals (lib/proposals.py); nothing here reads or writes the store directly.

function Tag({ children }) {
  return <span className="rounded-full bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">{children}</span>
}

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-3 text-sm">
      <span className="text-neutral-500">{label}</span>
      <span className="whitespace-pre-wrap break-words text-neutral-200">{children}</span>
    </div>
  )
}

function Modal({ title, subtitle, children }) {
  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label={title}>
      <div className="w-full max-w-md rounded-lg border border-neutral-800 bg-neutral-900 p-5">
        <h3 className="mb-1 font-mono text-sm font-semibold text-white">{title}</h3>
        <p className="mb-4 break-words text-xs text-neutral-500">{subtitle}</p>
        {children}
      </div>
    </div>
  )
}

const input = 'rounded-md border border-neutral-800 bg-neutral-950 p-1.5 text-sm text-neutral-200 placeholder:text-neutral-600'

function ModalButtons({ busy, onCancel, label, error }) {
  return (
    <>
      {error && <p role="alert" className="mb-2 text-sm text-red-400">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-neutral-400 hover:text-neutral-200 disabled:opacity-50">Cancel</button>
        <button type="submit" disabled={busy} className="rounded-md bg-amber-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-50">{busy ? 'Saving…' : label}</button>
      </div>
    </>
  )
}

export function DismissReason({ proposal, onSubmit, onCancel, busy, error }) {
  const [reason, setReason] = useState('')
  const [localError, setLocalError] = useState(null)
  return (
    <Modal title="Dismiss with reason" subtitle={proposal.title}>
      <form onSubmit={(e) => {
        e.preventDefault()
        const r = reason.trim()
        if (!r) return setLocalError('Say why, so MARVIN stops suggesting it.')
        if (r.length > 1000) return setLocalError('Keep it under 1000 characters.')
        setLocalError(null)
        onSubmit({ reason: r })
      }}>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={1000} autoFocus
          placeholder="e.g. Already covered by the Mac Mini migration" className={`mb-3 w-full ${input}`} />
        <ModalButtons busy={busy} onCancel={onCancel} label="Dismiss" error={localError || error} />
      </form>
    </Modal>
  )
}

export function DismissUntil({ proposal, onSubmit, onCancel, busy, error, today = new Date() }) {
  const [form, setForm] = useState({ mode: 'ticket', ticket: '', createTitle: '', text: '', backup: defaultBackup(today) })
  const [localError, setLocalError] = useState(null)
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))
  return (
    <Modal title="Dismiss until…" subtitle={proposal.title}>
      <form onSubmit={(e) => {
        e.preventDefault()
        const r = untilArgs(form, today)
        if (!r.ok) return setLocalError(r.error)
        setLocalError(null)
        onSubmit(r.args)
      }}>
        <label className="mb-2 flex items-start gap-2 text-sm text-neutral-300">
          <input type="radio" name="until" checked={form.mode !== 'text'} onChange={() => set({ mode: 'ticket' })} className="mt-1" />
          <span className="flex-1">A ticket is done
            {form.mode === 'create' ? (
              <span className="mt-1 flex gap-2">
                <input value={form.createTitle} onChange={(e) => set({ createTitle: e.target.value })} maxLength={500} autoFocus
                  placeholder="What the new ticket is for" className={`flex-1 ${input}`} />
                <button type="button" onClick={() => set({ mode: 'ticket' })} className="rounded-md border border-neutral-700 px-2 text-xs text-neutral-300">Use a number</button>
              </span>
            ) : (
              <span className="mt-1 flex gap-2">
                <input value={form.ticket} onChange={(e) => set({ ticket: e.target.value, mode: 'ticket' })} placeholder="#123" className={`w-24 ${input}`} />
                <button type="button" onClick={() => set({ mode: 'create' })} className="rounded-md border border-neutral-700 px-2 text-xs text-neutral-300">Create one</button>
              </span>
            )}
          </span>
        </label>
        <label className="mb-4 flex items-start gap-2 text-sm text-neutral-300">
          <input type="radio" name="until" checked={form.mode === 'text'} onChange={() => set({ mode: 'text' })} className="mt-1" />
          <span className="flex-1">Something exists (MARVIN checks each week)
            <input value={form.text} onChange={(e) => set({ text: e.target.value, mode: 'text' })} maxLength={500}
              placeholder="e.g. the local model runs on both Macs" className={`mt-1 w-full ${input}`} />
          </span>
        </label>
        <div className="mb-4 flex items-center gap-2 text-sm text-neutral-300">
          <span>Bring it back anyway on</span>
          <input type="date" value={form.backup} onChange={(e) => set({ backup: e.target.value })} className={input} />
        </div>
        <ModalButtons busy={busy} onCancel={onCancel} label="Dismiss until then" error={localError || error} />
      </form>
    </Modal>
  )
}

export function ProposalCard({ proposal: p, api, onDone, initialUi = {} }) {
  const [open, setOpen] = useState(!!initialUi.details)
  const [menu, setMenu] = useState(initialUi.menu || null) // null | 'snooze' | 'dismiss'
  const [dialog, setDialog] = useState(initialUi.dialog || null) // null | 'reason' | 'until'
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(initialUi.error || null)
  const [note, setNote] = useState(null)

  async function run(action, args) {
    setBusy(action)
    setError(null)
    setMenu(null)
    try {
      const r = await api.proposals.act(p.id, action, args)
      if (r?.ok) {
        setDialog(null)
        onDone(p.id, r.proposal)
      } else setError(r?.error || 'That didn’t work, and nothing was changed.')
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setBusy(null)
    }
  }

  async function ask() {
    setBusy('ask')
    setError(null)
    setNote(null)
    try {
      const r = await api.marvin.openSession({ proposal: p.id })
      if (r?.ok) setNote('Opened a MARVIN session with this proposal in WezTerm.')
      else setError(r?.error || 'Couldn’t open a session.')
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setBusy(null)
    }
  }

  const btn = 'rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-50'
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-5" data-proposal={p.id}>
      <div className="mb-3 flex items-start justify-between gap-4">
        <h3 className="break-words text-base font-medium text-white">{p.title}</h3>
        <span className="shrink-0 text-xs text-neutral-500">{[p.source, prettyDate(p.added)].filter(Boolean).join(' · ')}</span>
      </div>
      {p.returned && <p className="mb-3 text-xs text-amber-400" data-returned>Back again: {p.returned}</p>}
      <div className="mb-3 flex flex-col gap-2">
        <Row label="Problem">{p.problem}</Row>
        <Row label="Fix">{p.fix}</Row>
        <Row label="Why it matters">{p.why}</Row>
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {p.size && <Tag>{p.size}</Tag>}
        {p.area && <Tag>{p.area}</Tag>}
        <Tag>★ {p.north_star_name}</Tag>
      </div>
      {p.technical && (
        <>
          <button onClick={() => setOpen(!open)} className="mb-3 text-xs text-neutral-500 hover:text-neutral-300">{open ? '▾' : '▸'} Technical details</button>
          {open && <p className="mb-3 whitespace-pre-wrap break-words rounded-md bg-neutral-950 p-3 font-mono text-xs text-neutral-400">{p.technical}</p>}
        </>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button data-action="ticket" disabled={!!busy} onClick={() => run('ticket', {})}
          className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50">
          {busy === 'ticket' ? 'Making ticket…' : 'Make it a ticket'}
        </button>
        <button data-action="ask" disabled={!!busy} onClick={ask} className={btn}>{busy === 'ask' ? 'Opening…' : 'Ask MARVIN'}</button>
        <div className="relative">
          <button data-action="snooze" disabled={!!busy} onClick={() => setMenu(menu === 'snooze' ? null : 'snooze')} className={btn}>Snooze ▾</button>
          {menu === 'snooze' && (
            <div className="absolute left-0 top-9 z-10 w-36 rounded-md border border-neutral-800 bg-neutral-900 py-1 text-sm">
              {SNOOZE_OPTIONS.map((o) => (
                <button key={o.days} data-snooze={o.days} onClick={() => run('snooze', { days: o.days })} className="block w-full px-3 py-1.5 text-left text-neutral-300 hover:bg-neutral-800">{o.label}</button>
              ))}
            </div>
          )}
        </div>
        <div className="relative">
          <button data-action="dismiss" disabled={!!busy} onClick={() => setMenu(menu === 'dismiss' ? null : 'dismiss')} className="rounded-md px-3 py-1.5 text-sm text-neutral-400 hover:text-neutral-200 disabled:opacity-50">Dismiss ▾</button>
          {menu === 'dismiss' && (
            <div className="absolute left-0 top-9 z-10 w-48 rounded-md border border-neutral-800 bg-neutral-900 py-1 text-sm">
              <button data-dismiss="reason" onClick={() => { setMenu(null); setDialog('reason') }} className="block w-full px-3 py-1.5 text-left text-neutral-300 hover:bg-neutral-800">Dismiss with reason…</button>
              <button data-dismiss="until" onClick={() => { setMenu(null); setDialog('until') }} className="block w-full px-3 py-1.5 text-left text-neutral-300 hover:bg-neutral-800">Dismiss until…</button>
            </div>
          )}
        </div>
      </div>
      {error && !dialog && <p role="alert" className="mt-3 text-sm text-red-400">{error} Nothing was changed.</p>}
      {note && <p className="mt-3 text-sm text-emerald-400">{note}</p>}
      {dialog === 'reason' && <DismissReason proposal={p} busy={busy === 'dismiss'} error={error} onCancel={() => { setDialog(null); setError(null) }} onSubmit={(a) => run('dismiss', a)} />}
      {dialog === 'until' && <DismissUntil proposal={p} busy={busy === 'until'} error={error} onCancel={() => { setDialog(null); setError(null) }} onSubmit={(a) => run('until', a)} />}
    </div>
  )
}

function DoneRow({ item }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/50 px-5 py-3 text-sm" data-done={item.id}>
      <span className="text-emerald-400">✓ </span>
      <span className="text-neutral-300">{doneMessage(item)}</span>
      <span className="text-neutral-500"> · {item.title}</span>
      {item.status?.ticket && (
        <a href={`https://github.com/G-Eskayo/marvin/issues/${item.status.ticket}`} target="_blank" rel="noreferrer" className="ml-2 text-blue-400 hover:underline">Open #{item.status.ticket}</a>
      )}
    </div>
  )
}

export function ProposalsView({ state, api, onDone, onRetry, done = [] }) {
  // The list scrolls in its own box: switching to Open or Merged and back returns to the same proposal (#755).
  const box = useScrollArea('proposals')
  if (state.kind === 'loading') return <div className="p-6 text-sm text-neutral-500">Loading proposals…</div>
  if (state.kind === 'error') {
    return (
      <div className="p-6">
        <div role="alert" className="rounded-lg border border-red-700 bg-red-950/50 px-4 py-3 text-sm text-red-200">
          <p>Couldn’t load proposals. The proposals store didn’t answer on this Mac, so nothing is shown and nothing was changed.
            <button onClick={onRetry} className="ml-3 underline">Try again</button>
          </p>
          <p className="mt-1 break-words font-mono text-xs text-red-300/70">Details: {state.error}</p>
        </div>
      </div>
    )
  }
  const { proposals, problems } = state
  return (
    <div ref={box.ref} className="h-full overflow-y-auto p-6">
      <p className="mb-4 text-sm text-neutral-500">Big ideas MARVIN thinks are worth your time, each tied to a north star.</p>
      {problems.length > 0 && (
        <div role="alert" className="mb-4 max-w-4xl rounded-lg border border-amber-700 bg-amber-950/40 px-4 py-3 text-sm text-amber-200" data-problems>
          {problems.length === 1 ? '1 proposal' : `${problems.length} proposals`} couldn’t be read and {problems.length === 1 ? 'is' : 'are'} not shown:
          <ul className="mt-1 list-disc pl-5">
            {problems.slice(0, 5).map((x) => <li key={x.file}><span className="font-mono">{x.file}</span>: {x.error}</li>)}
          </ul>
          {problems.length > 5 && <p className="mt-1">…and {problems.length - 5} more.</p>}
        </div>
      )}
      <div className="flex max-w-4xl flex-col gap-4">
        {done.map((d) => <DoneRow key={`done-${d.id}`} item={d} />)}
        {proposals.length === 0 && (
          <div className="rounded-lg border border-dashed border-neutral-800 px-6 py-10 text-center" data-empty>
            <p className="text-neutral-300">No proposals right now</p>
            <p className="mt-1 text-sm text-neutral-500">Big ideas from the research colony, your projects and your own “idea: …” in chat will show up here.</p>
          </div>
        )}
        {proposals.map((p) => <ProposalCard key={p.id} proposal={p} api={api} onDone={onDone} />)}
      </div>
    </div>
  )
}

export default function ProposalsSection({ api = window.api, onCount }) {
  const [state, setState] = useState({ kind: 'loading' })
  const [done, setDone] = useState([])

  const load = useCallback(async () => {
    setState((s) => (s.kind === 'list' ? s : { kind: 'loading' }))
    try {
      const r = await api.proposals.list()
      if (r?.ok) setState({ kind: 'list', proposals: r.proposals, problems: r.problems })
      else setState({ kind: 'error', error: r?.error || 'no answer' })
    } catch (e) {
      setState({ kind: 'error', error: String(e?.message || e) })
    }
  }, [api])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (state.kind === 'list') onCount?.(state.proposals.length) }, [state, onCount])

  const onDone = (id, updated) => {
    setState((s) => (s.kind === 'list' ? { ...s, proposals: s.proposals.filter((p) => p.id !== id) } : s))
    setDone((d) => [updated, ...d.filter((x) => x.id !== id)])
  }

  return <ProposalsView state={state} api={api} onDone={onDone} onRetry={load} done={done} />
}
