import { STAGE_LABEL } from '../lib/stage_labels.js'

const money = (usd) => (usd ? `$${usd.toFixed(usd < 0.01 ? 4 : 2)}` : '$0.00')
const when = (iso) => {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export default function PipelineHistory({ events }) {
  if (!events || events.length === 0) return null

  const total = events.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
  const last = events[events.length - 1]

  return (
    <div className="mt-4">
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="text-xs uppercase tracking-wide text-neutral-500">Pipeline history</h3>
        <span className="font-mono text-xs text-neutral-400">
          now: {STAGE_LABEL[last.stage] || last.stage} ({last.status}) · total {money(total)}
        </span>
      </div>
      {events.map((e, i) => {
        const color = e.status === 'failed' ? 'text-red-400' : e.status === 'passed' ? 'text-emerald-400' : 'text-neutral-400'
        return (
          <div key={i} className="border-l-2 border-neutral-800 py-1.5 pl-4">
            <p className={`text-sm font-medium ${color}`}>
              {STAGE_LABEL[e.stage] || e.stage} — {e.status}
            </p>
            {e.detail && <p className="mt-0.5 whitespace-pre-wrap font-mono text-xs text-neutral-500">{e.detail}</p>}
            <p className="mt-0.5 text-xs text-neutral-600">
              {when(e.timestamp)} · {e.machine}
              {e.cost_usd != null ? ` · ${money(e.cost_usd)}` : ''}
            </p>
          </div>
        )
      })}
    </div>
  )
}
