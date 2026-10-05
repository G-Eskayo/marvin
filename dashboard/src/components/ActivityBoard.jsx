import { useEffect, useState } from 'react'
import ProjectBoard from './ProjectBoard.jsx'

const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Merge gate',
  merging: 'Merging',
  rebuilding: 'Rebuilding',
  done: 'Done'
}

function formatCost(usd) {
  if (!usd) return '$0.00'
  return `$${usd.toFixed(usd < 0.01 ? 4 : 2)}`
}

function formatTimestamp(iso) {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

function StatusDot({ status, failed, isLiveNow }) {
  const color = failed && status !== 'passed' ? 'bg-red-500' : isLiveNow ? 'bg-blue-500 animate-pulse' : status === 'passed' ? 'bg-emerald-500' : 'bg-neutral-600'
  return <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${color}`} />
}

function TicketRow({ ticket, onSelect }) {
  return (
    <button
      onClick={() => onSelect({ number: ticket.number, title: ticket.title })}
      className="flex w-full items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition-colors hover:border-neutral-700 hover:bg-neutral-800/50"
    >
      <StatusDot status={ticket.currentStatus} failed={ticket.failed} isLiveNow={ticket.isLiveNow} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-white">
          <span className="font-mono text-neutral-500">#{ticket.number}</span>{' '}
          {ticket.title || <span className="italic text-neutral-600">(title unknown)</span>}{' '}
          {ticket.isLiveNow && <span className="text-blue-400">· live now</span>}
        </p>
        <p className="text-xs text-neutral-500">
          {STAGE_LABEL[ticket.currentStage] || ticket.currentStage} · {ticket.eventCount} event{ticket.eventCount === 1 ? '' : 's'} · last{' '}
          {formatTimestamp(ticket.lastEventAt)}
        </p>
      </div>
      <span className="shrink-0 font-mono text-xs text-neutral-400">{formatCost(ticket.costUsd)}</span>
    </button>
  )
}

function TimelineEvent({ event }) {
  const color = event.status === 'failed' ? 'text-red-400' : event.status === 'passed' ? 'text-emerald-400' : 'text-neutral-400'
  return (
    <div className="flex gap-3 border-l-2 border-neutral-800 py-2 pl-4">
      <div className="flex-1">
        <p className={`text-sm font-medium ${color}`}>
          {STAGE_LABEL[event.stage] || event.stage} — {event.status}
        </p>
        {event.detail && <p className="mt-0.5 whitespace-pre-wrap font-mono text-xs text-neutral-500">{event.detail}</p>}
        <p className="mt-0.5 text-xs text-neutral-600">
          {formatTimestamp(event.timestamp)} · {event.machine}
          {event.cost_usd !== null && event.cost_usd !== undefined && ` · ${formatCost(event.cost_usd)}`}
        </p>
      </div>
    </div>
  )
}

function TicketDrilldown({ number, title, onBack }) {
  const [events, setEvents] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    window.api.activity
      .timeline(number)
      .then(setEvents)
      .catch((err) => setError(String(err)))
  }, [number])

  const totalCost = events ? events.reduce((sum, e) => sum + (e.cost_usd || 0), 0) : 0

  return (
    <div className="p-6">
      <button onClick={onBack} className="mb-4 text-sm text-neutral-400 hover:text-neutral-200">
        ← Back to Activity
      </button>
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-white">
          <span className="font-mono text-neutral-500">#{number}</span> {title || <span className="italic text-neutral-600">(title unknown)</span>}
        </h2>
        {events && <span className="font-mono text-sm text-neutral-400">total: {formatCost(totalCost)}</span>}
      </div>

      {error && <p className="text-red-400">Failed to load: {error}</p>}
      {!error && events === null && <p className="text-neutral-500">Loading…</p>}
      {!error && events !== null && events.length === 0 && <p className="text-neutral-500">No events recorded for this ticket.</p>}
      {events && events.length > 0 && (
        <div className="max-w-2xl">
          {events.map((event, i) => (
            <TimelineEvent key={i} event={event} />
          ))}
        </div>
      )}
    </div>
  )
}

function PipelineLog() {
  const [tickets, setTickets] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  function load() {
    window.api.activity
      .list()
      .then((result) => {
        setTickets(result)
        setError(null)
      })
      .catch((err) => setError(String(err)))
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 120_000) // backstop; triggers below do the real work
    const off = window.api.triggers.on((t) => t.topic === 'activity' && load())
    return () => {
      clearInterval(interval)
      off()
    }
  }, [])

  if (selected !== null) {
    return <TicketDrilldown number={selected.number} title={selected.title} onBack={() => setSelected(null)} />
  }

  if (error) {
    return <div className="flex h-full items-center justify-center text-red-400">Failed to load activity: {error}</div>
  }
  if (tickets === null) {
    return <div className="flex h-full items-center justify-center text-neutral-500">Loading…</div>
  }

  const totalCost = tickets.reduce((sum, t) => sum + (t.costUsd || 0), 0)

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm uppercase tracking-wide text-neutral-500">Ticket pipeline activity</h2>
        <span className="font-mono text-sm text-neutral-400">tracked usage: {formatCost(totalCost)}</span>
      </div>
      {tickets.length === 0 ? (
        <div className="flex h-64 flex-col items-center justify-center gap-2 text-center text-neutral-500">
          <p className="text-lg font-medium text-neutral-300">No ticket activity recorded yet</p>
          <p className="max-w-md text-sm">
            Fills in automatically as the ticket pipeline claims, plans, executes, and merges work —
            each stage this records as it happens, not just the live snapshot.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {tickets.map((ticket) => (
            <TicketRow key={ticket.number} ticket={ticket} onSelect={setSelected} />
          ))}
        </div>
      )}
    </div>
  )
}

// Activity tab: per-project Jira-style boards first; the flat pipeline log
// (per-ticket stages + cost) stays as its own view.
export default function ActivityBoard({ onOpenMr, onOpenDocs, nav }) {
  const [view, setView] = useState('boards')
  return (
    <div>
      <div className="flex gap-1 px-6 pt-4">
        {[['boards', 'Boards'], ['log', 'Pipeline log']].map(([id, label]) => (
          <button
            key={id}
            onClick={() => setView(id)}
            className={`rounded px-3 py-1 text-sm ${view === id ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            {label}
          </button>
        ))}
      </div>
      {view === 'boards' ? <ProjectBoard onOpenMr={onOpenMr} onOpenDocs={onOpenDocs} nav={nav} /> : <PipelineLog />}
    </div>
  )
}
