import { useRef, useState } from 'react'
import { describeMachines } from '../lib/running_view.js'

// Hover the top-right activity badge to see everything that is running, on every machine, against each machine's slots,
// and what the scanner will start next. The badge itself still shows the first thing; this is the rest of it.
export default function ActivityHover({ children }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(null)
  const timer = useRef(null)

  const show = () => {
    clearTimeout(timer.current)
    setOpen(true)
    Promise.all([window.api.queue.list(), window.api.dispatch.getConcurrency()])
      .then(([q, settings]) => setData({ q, settings }))
      .catch((e) => setData({ error: String(e.message || e) }))
  }
  const hide = () => { timer.current = setTimeout(() => setOpen(false), 150) }

  return (
    <div className="relative" onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-[26rem] rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-xs shadow-xl" data-testid="activity-hover">
          {!data && <p className="text-neutral-500">Loading…</p>}
          {data?.error && <p className="text-red-400">{data.error}</p>}
          {data?.q && (
            <>
              <p className="mb-1 font-medium text-neutral-300">
                Running {data.settings?.parallel ? '' : <span className="font-normal text-neutral-500">(parallel is off: one per machine)</span>}
              </p>
              {data.q.error && <p className="text-red-400">{data.q.error}</p>}
              {describeMachines({ running: data.q.running, settings: data.settings }).map((m) => (
                <div key={m.machine} className="mb-1">
                  <p className="text-neutral-400">{m.machine} <span className="text-neutral-600">{m.used} of {m.limit}</span></p>
                  {m.tickets.length === 0 && <p className="pl-3 text-neutral-600">idle</p>}
                  {m.tickets.map((t) => <p key={t} className="truncate pl-3 text-neutral-200">{t}</p>)}
                </div>
              ))}
              <p className="mb-1 mt-2 font-medium text-neutral-300">Next up <span className="font-normal text-neutral-500">· {data.q.queue.length} ready</span></p>
              {data.q.queue.length === 0 && <p className="text-neutral-600">nothing waiting</p>}
              {data.q.queue.slice(0, 4).map((r) => (
                <p key={`${r.repo}#${r.number}`} className="truncate text-neutral-300">
                  <span className="mr-1 text-neutral-600">{r.position}</span>{r.project} #{r.number} {r.title}
                </p>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}
