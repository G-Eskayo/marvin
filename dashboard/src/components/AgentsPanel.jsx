import { useEffect, useState } from 'react'
import TicketAgentsPanel from './TicketAgentsPanel.jsx'
import ProfilesPanel from './ProfilesPanel.jsx'

const DOT = {
  running: 'bg-blue-500 animate-pulse',
  stopped: 'bg-red-500',
  idle: 'bg-emerald-500',
  failed: 'bg-red-500',
  crashed: 'bg-red-500',
  never: 'bg-neutral-600'
}
const STATUS_TEXT = { running: 'Running', idle: 'Idle', failed: 'Last run failed', crashed: 'Stopped unexpectedly', stopped: 'Not running', never: 'Has not run yet' }
const KIND_TEXT = { scheduled: 'scheduled', service: 'always-on service', job: 'sub-job' }

function ago(iso, now) {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

const dur = (s) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`)

function RunHistory({ runs, now }) {
  return (
    <div className="mt-3 flex flex-col gap-2">
      {runs.map((r) => (
        <div key={r.id} className="rounded border border-neutral-800 p-2">
          <p className={`text-xs ${r.status === 'failed' ? 'text-red-400' : r.status === 'running' ? 'text-blue-400' : 'text-neutral-400'}`}>
            {r.status} · started {ago(r.started_at, now)}
            {r.finished_at ? ` · took ${dur(Math.round((Date.parse(r.finished_at) - Date.parse(r.started_at)) / 1000))}` : ''}
            {r.summary ? ` · ${r.summary}` : ''}
          </p>
          {r.error && <p className="text-xs text-red-400">{r.error}</p>}
          <ol className="mt-1 border-l border-neutral-800 pl-3">
            {r.steps.map((s, i) => (
              <li key={i} className="text-[11px] text-neutral-500">
                <span className="text-neutral-300">{s.step}</span>
                {s.detail ? ` — ${s.detail}` : ''}
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  )
}

function AgentCard({ agent, now }) {
  const [open, setOpen] = useState(false)
  const job = agent.job
  const bad = agent.status === 'failed' || agent.status === 'crashed' || agent.status === 'stopped'
  return (
    <div className={`rounded-lg border bg-neutral-900 p-4 ${bad ? 'border-red-900' : 'border-neutral-800'}`}>
      <button onClick={() => job && setOpen(!open)} className={`flex w-full items-start gap-3 text-left ${job ? '' : 'cursor-default'}`}>
        <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${DOT[agent.status] || DOT.never}`} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-white">
            {agent.label}
            <span className={`ml-2 text-xs font-normal ${bad ? 'text-red-400' : 'text-neutral-500'}`}>{STATUS_TEXT[agent.status]}</span>
            <span className="ml-2 text-[11px] font-normal text-neutral-600">
              {KIND_TEXT[agent.kind]} · {agent.schedule}
              {agent.pid ? ` · pid ${agent.pid}` : ''}
            </span>
          </p>
          {job?.current && (
            <p className="mt-0.5 text-sm text-blue-300">
              {job.current.step}
              {job.current.detail ? <span className="text-neutral-400"> — {job.current.detail}</span> : null}
              <span className="ml-2 text-xs text-neutral-500">{dur(Math.max(0, Math.round((now - Date.parse(job.current.startedAt)) / 1000)))} so far</span>
            </p>
          )}
          {job?.last && (
            <p className={`mt-0.5 text-xs ${job.last.status === 'failed' ? 'text-red-400' : 'text-neutral-500'}`}>
              Last run {ago(job.last.finishedAt, now)}, took {dur(job.last.durationS)}
              {job.last.summary ? ` — ${job.last.summary}` : ''}
              {job.last.error ? ` — ${job.last.error}` : ''}
            </p>
          )}
          {!agent.reporting && (
            <p className="mt-0.5 text-xs text-neutral-600">
              Not reporting steps yet: all we know is launchd's last exit code ({agent.lastExit ?? 'unknown'}). It starts reporting on its next run.
            </p>
          )}
        </div>
        {job && <span className="text-xs text-neutral-600">{open ? 'hide' : 'history'}</span>}
      </button>
      {open && job && <RunHistory runs={job.runs} now={now} />}
    </div>
  )
}

export default function AgentsPanel({ agents }) {
  const [now, setNow] = useState(Date.now())
  const anyRunning = agents?.some((a) => a.status === 'running')
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), anyRunning ? 1000 : 30_000)
    return () => clearInterval(id)
  }, [anyRunning])

  if (agents === null) return <div className="p-6 text-neutral-500">Loading…</div>
  const reporting = agents.filter((a) => a.reporting).length
  return (
    <div className="max-w-3xl">
      <ProfilesPanel />
      <TicketAgentsPanel />
      <p className="mb-3 text-xs text-neutral-500">
        Every autonomous agent on this machine: what launchd says (schedule, running now, last exit) and what the agent reports about itself
        (current step, recent runs). {reporting} of {agents.length} report steps; the rest start reporting at their next run.
      </p>
      <div className="flex flex-col gap-2">
        {agents.map((a) => (
          <AgentCard key={a.id} agent={a} now={now} />
        ))}
      </div>
    </div>
  )
}
