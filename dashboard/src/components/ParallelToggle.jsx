import { useEffect, useState } from 'react'
import { capacity, describeMachines } from '../lib/running_view.js'

// The cost note shown when parallel is on (ADR 0052): the extra model usage is the thing to decide on.
export const COST_NOTE = 'About $1.39 per ticket at the median, so two at once spend your plan about twice as fast.'

// What the control says, from the saved settings. Pure so it is tested without a window.
export function describeParallel(s) {
  if (!s) return { on: false, summary: 'Loading…', note: null, capNote: null }
  if (!s.parallel) return { on: false, summary: 'Off: one ticket per machine at a time', note: null, capNote: null }
  const cap = capacity(s)
  const machines = Object.entries(s.machine_slots || {}).map(([m, n]) => `${m} ${n}`).join(', ')
  return {
    on: true,
    summary: `On: up to ${cap} at once, ${s.max_per_project} per project`,
    note: COST_NOTE,
    capNote: s.max_total > cap
      ? `Your machines only hold ${cap} at once (${machines}), so ${s.max_total} runs as ${cap}.`
      : `Your machines hold ${cap} at once (${machines}).`
  }
}

function LimitInput({ label, value, onApply }) {
  const [draft, setDraft] = useState(String(value ?? ''))
  useEffect(() => setDraft(String(value ?? '')), [value])
  const apply = () => { if (draft !== String(value)) onApply(Number(draft), () => setDraft(String(value))) }
  return (
    <label className="flex items-center gap-2 text-xs text-neutral-400">
      {label}
      <input
        type="number" min="1" max="8" value={draft} aria-label={label}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={apply}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        className="w-14 rounded border border-neutral-600 bg-neutral-950 px-2 py-1 text-center text-sm text-neutral-100"
      />
    </label>
  )
}

export default function ParallelToggle() {
  const [s, setS] = useState(null)
  const [running, setRunning] = useState([])
  const [error, setError] = useState(null)
  const [scan, setScan] = useState(null)

  useEffect(() => {
    window.api.dispatch.getConcurrency().then(setS).catch((e) => setError(String(e.message || e)))
    window.api.queue.list().then((r) => setRunning(r.running || [])).catch(() => {})
  }, [])

  const clean = (e) => String(e.message || e).replace(/^Error invoking remote method '[^']*': (Error: )?/, '')
  const save = (patch, revert) =>
    window.api.dispatch
      .setConcurrency({ ...s, ...patch })
      .then((saved) => { setS(saved); setError(null); if (patch.parallel) setScan('A scan was started: tickets begin within a minute.') })
      .catch((e) => { setError(clean(e)); revert?.() })
  const scanNow = () => window.api.dispatch.scanNow().then(() => setScan('A scan was started: tickets begin within a minute.')).catch((e) => setError(clean(e)))

  const v = describeParallel(s)
  return (
    <div className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 p-3" data-testid="parallel-toggle">
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <span className="font-medium text-neutral-200">Parallel tickets</span>
        <button
          role="switch" aria-checked={v.on} disabled={!s}
          onClick={() => save({ parallel: !s.parallel })}
          className={`rounded-full px-4 py-1 text-xs font-medium ${v.on ? 'bg-blue-600 text-white' : 'bg-neutral-800 text-neutral-400'}`}
        >
          {v.on ? 'On' : 'Off'}
        </button>
        {v.on && (
          <>
            <LimitInput label="Tickets at once" value={s.max_total} onApply={(n, revert) => save({ max_total: n }, revert)} />
            <LimitInput label="Per project" value={s.max_per_project} onApply={(n, revert) => save({ max_per_project: n }, revert)} />
            <button onClick={scanNow} className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-800" title="Start a scan now instead of waiting for the hourly one">
              Scan now
            </button>
          </>
        )}
        <span className="ml-auto text-xs text-neutral-500">{v.summary}</span>
      </div>
      {v.on && <p className="mt-2 text-xs text-neutral-400">{v.capNote} Running now: {running.length}.</p>}
      {v.note && <p className="mt-1 text-xs text-amber-400">{v.note}</p>}
      {scan && <p className="mt-1 text-xs text-blue-300">{scan}</p>}
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
    </div>
  )
}
