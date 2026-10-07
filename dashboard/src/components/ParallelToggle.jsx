import { useEffect, useState } from 'react'

// The cost note shown when parallel is on (ADR 0052): the extra model usage is the thing to decide on.
export const COST_NOTE = 'About $1.39 per ticket at the median, so two at once spend your plan about twice as fast.'

// What the control says, from the saved settings. Pure so it is tested without a window.
export function describeParallel(s) {
  if (!s) return { on: false, summary: 'Loading…', note: null }
  if (!s.parallel) return { on: false, summary: 'Off: one ticket per machine at a time', note: null }
  return { on: true, summary: `On: up to ${s.max_total} at once, ${s.max_per_project} per project`, note: COST_NOTE }
}

export default function ParallelToggle() {
  const [s, setS] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    window.api.dispatch.getConcurrency().then(setS).catch((e) => setError(String(e.message || e)))
  }, [])

  const save = (patch) =>
    window.api.dispatch
      .setConcurrency({ ...s, ...patch })
      .then((saved) => { setS(saved); setError(null) })
      .catch((e) => setError(String(e.message || e).replace(/^Error invoking remote method '[^']*': (Error: )?/, '')))

  const v = describeParallel(s)
  const num = (key) => (
    <input
      type="number" min="1" max="8" value={s?.[key] ?? ''}
      onChange={(e) => save({ [key]: Number(e.target.value) })}
      className="w-12 rounded border border-neutral-700 bg-neutral-950 px-1 text-center text-neutral-200"
    />
  )
  return (
    <div className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 p-3" data-testid="parallel-toggle">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-neutral-200">Parallel tickets</span>
        <button
          role="switch" aria-checked={v.on} disabled={!s}
          onClick={() => save({ parallel: !s.parallel })}
          className={`rounded-full px-3 py-0.5 text-xs ${v.on ? 'bg-blue-600 text-white' : 'bg-neutral-800 text-neutral-400'}`}
        >
          {v.on ? 'On' : 'Off'}
        </button>
        {v.on && (
          <span className="flex items-center gap-2 text-xs text-neutral-400">
            up to {num('max_total')} at once, {num('max_per_project')} per project
          </span>
        )}
        <span className="ml-auto text-xs text-neutral-500">{v.summary}</span>
      </div>
      {v.note && <p className="mt-2 text-xs text-amber-400">{v.note}</p>}
      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
    </div>
  )
}
