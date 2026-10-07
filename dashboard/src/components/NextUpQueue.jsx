import { useEffect, useState } from 'react'

const POLL_MS = 60000

// One line per queued ticket, in the order the scanner will dispatch it (ADR 0053). Number always travels with its title.
export function describeQueueRow(r) {
  return {
    key: `${r.repo}#${r.number}`,
    next: r.position === 1,
    label: `${r.project} #${r.number} ${r.title}`,
    priority: r.priority ? r.priority.toUpperCase() : null,
    machines: r.machines?.length ? r.machines.join(', ') : 'any machine'
  }
}

export default function NextUpQueue({ onOpenTicket }) {
  const [state, setState] = useState({ queue: null, error: null })
  const [open, setOpen] = useState(true)

  useEffect(() => {
    let cancelled = false
    const refresh = () => window.api.queue.list().then((r) => !cancelled && setState(r)).catch((e) => !cancelled && setState({ queue: [], error: String(e.message || e) }))
    refresh()
    const i = setInterval(refresh, POLL_MS)
    return () => { cancelled = true; clearInterval(i) }
  }, [])

  const { queue, error } = state
  return (
    <section className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900" data-testid="next-up">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between p-3 text-left">
        <span className="text-sm font-medium text-neutral-200">
          Next up <span className="text-neutral-500">{queue ? `· ${queue.length} ready` : ''}</span>
        </span>
        <span className="text-xs text-neutral-500">{open ? 'hide' : 'show'}</span>
      </button>
      {open && (
        <div className="border-t border-neutral-800 p-3">
          {error && <p className="text-xs text-red-400">{error}</p>}
          {!queue && !error && <p className="text-xs text-neutral-500">Loading…</p>}
          {queue && !error && queue.length === 0 && <p className="text-xs text-neutral-500">Nothing is waiting: no ready, unblocked ticket in any project.</p>}
          {queue && queue.length > 0 && (
            <ol className="space-y-1">
              {queue.slice(0, 12).map((r) => {
                const v = describeQueueRow(r)
                return (
                  <li key={v.key} className="flex items-baseline gap-2 text-sm">
                    <span className="w-5 shrink-0 text-right text-xs text-neutral-600">{r.position}</span>
                    <button onClick={() => onOpenTicket?.(r.repo, r.number)} className={`truncate text-left hover:text-white ${v.next ? 'text-neutral-100' : 'text-neutral-300'}`}>
                      {v.label}
                    </button>
                    {v.next && <span className="shrink-0 rounded bg-blue-900/50 px-1.5 text-[10px] text-blue-300">next scan</span>}
                    {v.priority && <span className="shrink-0 text-[10px] text-amber-400">{v.priority}</span>}
                    <span className="ml-auto shrink-0 text-xs text-neutral-600">{v.machines}</span>
                  </li>
                )
              })}
              {queue.length > 12 && <li className="text-xs text-neutral-600">and {queue.length - 12} more</li>}
            </ol>
          )}
        </div>
      )}
    </section>
  )
}
