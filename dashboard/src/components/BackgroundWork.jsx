import { useEffect, useState } from 'react'

const DOT = {
  running: 'bg-blue-500 animate-pulse',
  idle: 'bg-emerald-500',
  failed: 'bg-red-500',
  crashed: 'bg-red-500',
  never: 'bg-neutral-600'
}
const STATUS_TEXT = { running: 'Running', idle: 'Idle', failed: 'Last run failed', crashed: 'Stopped unexpectedly', never: 'Has not run yet' }

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

function JobCard({ job, now }) {
  const [open, setOpen] = useState(false)
  const bad = job.status === 'failed' || job.status === 'crashed'
  return (
    <div className={`rounded-lg border bg-neutral-900 p-4 ${bad ? 'border-red-900' : 'border-neutral-800'}`}>
      <button onClick={() => setOpen(!open)} className="flex w-full items-start gap-3 text-left">
        <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${DOT[job.status]}`} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-white">
            {job.label} <span className={`ml-2 text-xs font-normal ${bad ? 'text-red-400' : 'text-neutral-500'}`}>{STATUS_TEXT[job.status]}</span>
          </p>
          {job.current && (
            <p className="mt-0.5 text-sm text-blue-300">
              {job.current.step}
              {job.current.detail ? <span className="text-neutral-400"> — {job.current.detail}</span> : null}
              <span className="ml-2 text-xs text-neutral-500">{dur(Math.max(0, Math.round((now - Date.parse(job.current.startedAt)) / 1000)))} so far</span>
            </p>
          )}
          {job.last && (
            <p className={`mt-0.5 text-xs ${job.last.status === 'failed' ? 'text-red-400' : 'text-neutral-500'}`}>
              Last run {ago(job.last.finishedAt, now)}, took {dur(job.last.durationS)}
              {job.last.summary ? ` — ${job.last.summary}` : ''}
              {job.last.error ? ` — ${job.last.error}` : ''}
            </p>
          )}
        </div>
        <span className="text-xs text-neutral-600">{open ? 'hide' : 'history'}</span>
      </button>
      {open && <RunHistory runs={job.runs} now={now} />}
    </div>
  )
}

export default function BackgroundWork({ jobs }) {
  const [now, setNow] = useState(Date.now())
  const anyRunning = jobs?.some((j) => j.status === 'running')
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), anyRunning ? 1000 : 30_000)
    return () => clearInterval(id)
  }, [anyRunning])

  if (jobs === null) return <div className="p-6 text-neutral-500">Loading…</div>
  if (jobs.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-center text-neutral-500">
        <p className="text-lg font-medium text-neutral-300">No background work recorded yet</p>
        <p className="max-w-md text-sm">Jobs show up here the first time they run: the hourly ticket scan, the project catalog, the daily tidy-up, the dashboard rebuild check.</p>
      </div>
    )
  }
  return (
    <div className="max-w-3xl p-6">
      <p className="mb-3 text-xs text-neutral-500">What MARVIN's background jobs are doing on this machine, live. Click a job for its recent runs and the steps of each.</p>
      <div className="flex flex-col gap-2">
        {jobs.map((j) => (
          <JobCard key={j.job} job={j} now={now} />
        ))}
      </div>
    </div>
  )
}
