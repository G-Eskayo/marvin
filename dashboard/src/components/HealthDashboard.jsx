import { useEffect, useState } from 'react'
import HealthDrilldown from './HealthDrilldown.jsx'
import AgentsPanel from './AgentsPanel.jsx'

// How long a check is trusted at full color before it starts visually
// greying out (ADR 0033's Staleness gradient term). All v1 checks run in
// one sweep every 15 minutes (see com.marvin.health-check), so one shared
// tolerance is honest about what this build actually does -- true
// per-check tolerance (a daily check staying "fresh" far longer than a
// storm-detection check) is a real extension for whenever checks start
// running on genuinely different schedules, not simulated here.
const STALE_AFTER_MS = 30 * 60 * 1000

const SEVERITY_COLOR = {
  red: { bg: 'bg-red-950', border: 'border-red-900', dot: 'bg-red-500', text: 'text-red-300' },
  yellow: { bg: 'bg-amber-950', border: 'border-amber-900', dot: 'bg-amber-500', text: 'text-amber-300' },
  green: { bg: 'bg-emerald-950', border: 'border-emerald-900', dot: 'bg-emerald-500', text: 'text-emerald-300' },
  // "asleep" = a laptop that is simply closed/away (Tailscale offline, recent) -- neutral,
  // blue + moon, deliberately NOT red: red means "needs your immediate attention".
  asleep: { bg: 'bg-sky-950', border: 'border-sky-900', dot: 'bg-sky-400', text: 'text-sky-300' },
  unmonitored: { bg: 'bg-neutral-900', border: 'border-neutral-700', dot: 'bg-neutral-600', text: 'text-neutral-400' }
}

function MoonIcon({ className = '' }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-label="asleep"
      role="img"
      className={`h-3.5 w-3.5 shrink-0 fill-sky-300 ${className}`}
    >
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  )
}

function stalenessOpacity(checkedAt) {
  if (!checkedAt) return 0.35 // never checked at all -- near-fully grey
  const ageMs = Date.now() - new Date(checkedAt).getTime()
  if (ageMs <= STALE_AFTER_MS) return 1
  // Linear fade from full color at STALE_AFTER_MS to mostly-grey by 4x that.
  const fadeRange = STALE_AFTER_MS * 3
  const fraction = Math.min(1, (ageMs - STALE_AFTER_MS) / fadeRange)
  return 1 - fraction * 0.65
}

function CheckCard({ check, onClick }) {
  const colors = SEVERITY_COLOR[check.severity] ?? SEVERITY_COLOR.unmonitored
  const opacity = stalenessOpacity(check.checked_at)
  return (
    <button
      onClick={onClick}
      style={{ opacity }}
      className={`flex flex-col gap-2 rounded-lg border ${colors.border} ${colors.bg} p-4 text-left transition-opacity hover:opacity-100`}
    >
      <div className="flex items-center gap-2">
        {check.severity === 'asleep' ? (
          <MoonIcon />
        ) : (
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${colors.dot}`} />
        )}
        <h3 className="truncate text-sm font-medium text-white">{check.label}</h3>
      </div>
      <p className={`line-clamp-2 text-xs ${colors.text}`}>{check.detail}</p>
    </button>
  )
}

function UnmonitoredCard({ jobName, onClick }) {
  const colors = SEVERITY_COLOR.unmonitored
  return (
    <button
      onClick={onClick}
      className={`flex flex-col gap-2 rounded-lg border border-dashed ${colors.border} ${colors.bg} p-4 text-left opacity-70 transition-opacity hover:opacity-100`}
    >
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${colors.dot}`} />
        <h3 className="truncate text-sm font-medium text-neutral-300">{jobName}</h3>
      </div>
      <p className="text-xs text-neutral-500">No check registered — real job, zero coverage</p>
    </button>
  )
}

function OverallBadge({ overall, generatedAt, refreshing, onRefresh }) {
  const colors = SEVERITY_COLOR[overall] ?? SEVERITY_COLOR.unmonitored
  return (
    <div className="mb-4 flex items-center gap-3">
      <span className={`flex items-center gap-2 rounded-md ${colors.bg} ${colors.border} border px-3 py-1.5 text-sm font-medium ${colors.text}`}>
        <span className={`h-2 w-2 rounded-full ${colors.dot}`} />
        {overall === 'red' ? 'Something is broken' : overall === 'yellow' ? 'Degraded' : 'All checks healthy'}
      </span>
      <span className="text-xs text-neutral-500">
        last run: {generatedAt ? new Date(generatedAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'never'}
      </span>
      <button
        onClick={onRefresh}
        disabled={refreshing}
        className="ml-auto rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:border-neutral-500 disabled:opacity-50"
      >
        {refreshing ? 'Refreshing…' : 'Refresh now'}
      </button>
    </div>
  )
}

export default function HealthDashboard({ nav }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [view, setView] = useState('checks')
  // A click on the header's working indicator lands on the agents list.
  useEffect(() => {
    if (nav?.tab === 'health' && nav.view) setView(nav.view)
  }, [nav?.at])
  const [agents, setAgents] = useState(null)

  // Agents refresh by trigger (the run-log folder is watched); the poll is only a backstop.
  useEffect(() => {
    const loadAgents = () => window.api.health.agents().then(setAgents).catch(() => {})
    loadAgents()
    const id = setInterval(loadAgents, 60_000)
    const off = window.api.triggers.on((t) => t.topic === 'agents' && loadAgents())
    return () => {
      clearInterval(id)
      off()
    }
  }, [])

  function load() {
    window.api.health
      .status()
      .then((result) => {
        setStatus(result)
        setError(null)
      })
      .catch((err) => setError(String(err)))
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 60_000) // live-refresh the view against the on-disk snapshot
    return () => clearInterval(interval)
  }, [])

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await window.api.health.refresh?.()
    } finally {
      load()
      setRefreshing(false)
    }
  }

  if (error) {
    return <div className="flex h-full items-center justify-center text-red-400">Failed to load health status: {error}</div>
  }
  if (!status) {
    return <div className="flex h-full items-center justify-center text-neutral-500">Loading…</div>
  }

  if (selected) {
    return <HealthDrilldown check={selected} onBack={() => setSelected(null)} />
  }

  const cov = status.coverage
  const agentProblems = agents?.filter((a) => ['failed', 'crashed', 'stopped'].includes(a.status)).length || 0
  const agentsRunning = agents?.filter((a) => a.status === 'running').length || 0
  return (
    <div className="p-6">
      <div className="mb-4 flex gap-1">
        {[['checks', 'Checks'], ['agents', 'Autonomous agents']].map(([id, label]) => (
          <button
            key={id}
            onClick={() => setView(id)}
            className={`rounded px-3 py-1 text-sm ${view === id ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            {label}
            {id === 'agents' && agentsRunning > 0 && <span className="ml-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" title={`${agentsRunning} running`} />}
            {id === 'agents' && agentProblems > 0 && <span className="ml-1.5 inline-block h-2 w-2 rounded-full bg-red-500" title={`${agentProblems} need attention`} />}
          </button>
        ))}
      </div>
      {view === 'agents' ? (
        <AgentsPanel agents={agents} />
      ) : (
      <>
      <OverallBadge overall={status.overall} generatedAt={status.generated_at} refreshing={refreshing} onRefresh={handleRefresh} />

      {cov && (
        <p className="mb-4 text-xs text-neutral-500">
          coverage: {cov.covered}/{cov.total} known subsystems have a registered check
          {cov.fraction < 1 && ` (${cov.unmonitored_jobs.length} unmonitored below)`}
        </p>
      )}

      {status.checks.length === 0 ? (
        <div className="flex h-64 flex-col items-center justify-center gap-2 text-center text-neutral-500">
          <p className="text-lg font-medium text-neutral-300">No health data yet</p>
          <p className="max-w-md text-sm">
            Fills in automatically once{' '}
            <code className="rounded bg-neutral-800 px-1 py-0.5 text-neutral-300">health_checks.py</code> has run once —
            every 15 minutes via com.marvin.health-check, or click Refresh now.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {status.checks.map((check) => (
            <CheckCard key={check.id} check={check} onClick={() => setSelected(check)} />
          ))}
          {cov?.unmonitored_jobs.map((name) => (
            <UnmonitoredCard key={name} jobName={name} onClick={() => {}} />
          ))}
        </div>
      )}
      </>
      )}
    </div>
  )
}
