import { useEffect, useState } from 'react'
import HealthDrilldown from './HealthDrilldown.jsx'
import AgentsPanel from './AgentsPanel.jsx'
import ProjectReadinessPanel from './ProjectReadinessPanel.jsx'
import SafetyReviews from './SafetyReviews.jsx'
import { healthFocus } from '../lib/boot_view.js'

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
      data-check-id={check.id}
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

// marvin#422: errors are never silent. Every kind of error on either Mac in the last 24 hours, folded, newest first:
// machine · where · plain cause · how many times · when. Red while it keeps repeating within the hour.
function ago(t, now) {
  const m = Math.round((now - Date.parse(t)) / 60_000)
  if (!Number.isFinite(m)) return ''
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
}

export function RecentErrors({ errors, now = Date.now() }) {
  if (!Array.isArray(errors)) return null
  return (
    <section className="mt-6">
      <h3 className="mb-2 text-sm font-medium text-neutral-200">Recent errors</h3>
      {errors.length === 0 ? (
        <p className="text-sm text-neutral-500">No errors in the last 24 hours on either Mac.</p>
      ) : (
        <ul className="divide-y divide-neutral-800 rounded-lg border border-neutral-800">
          {errors.map((e) => (
            <li key={`${e.machine}|${e.source}|${e.cause}`} data-severity={e.severity} className="flex flex-col gap-0.5 px-3 py-2 text-sm">
              <div className="flex items-baseline gap-2">
                <span className={`h-2 w-2 shrink-0 rounded-full ${e.severity === 'red' ? 'bg-red-500' : 'bg-amber-400'}`} />
                <span className="font-medium text-neutral-100">{e.cause}</span>
                <span className="ml-auto shrink-0 text-xs text-neutral-500">×{e.count} · {ago(e.last_t, now)}</span>
              </div>
              <div className="pl-4 text-xs text-neutral-400">{e.machine} · <span className="font-mono">{e.source}</span>{e.message ? ` · ${e.message}` : ''}</div>
              {e.raw && <pre className="ml-4 mt-1 max-h-24 overflow-auto whitespace-pre-wrap rounded bg-neutral-900 p-2 font-mono text-[11px] text-neutral-500">{e.raw}</pre>}
            </li>
          ))}
        </ul>
      )}
    </section>
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
  const [focus, setFocus] = useState(null) // { id, at }: the check to scroll to and flash once (#433)
  // A click on the header's working indicator lands on the agents list.
  useEffect(() => {
    if (nav?.tab === 'health' && nav.view) setView(nav.view)
    // The boot's summary lines land on the exact check behind them (#433): Checks view, scrolled to it, one flash.
    const id = healthFocus(nav)
    if (id) { setView('checks'); setFocus({ id, at: nav.at }) }
  }, [nav?.at])
  useEffect(() => {
    if (!focus || !status || view !== 'checks') return
    const card = document.querySelector(`[data-check-id="${CSS.escape(focus.id)}"]`)
    if (card) {
      card.scrollIntoView({ block: 'center', behavior: 'smooth' })
      card.animate([{ boxShadow: '0 0 0 2px #ff6a1f, 0 0 22px #ff6a1f99' }, { boxShadow: '0 0 0 2px #ff6a1f, 0 0 22px #ff6a1f99', offset: 0.35 }, { boxShadow: '0 0 0 0 transparent' }], { duration: 1600, easing: 'ease-out' })
    }
    setFocus(null)
  }, [focus, status, view])
  const [agents, setAgents] = useState(null)
  const [readiness, setReadiness] = useState(null)
  const [profiles, setProfiles] = useState(null)
  const [readinessLoading, setReadinessLoading] = useState(false)
  // Safety reviews: read on open and whenever quarantine.md changes (the 'quarantine' trigger); the count labels the view.
  const [reviews, setReviews] = useState(null)
  const loadReviews = () => window.api.safety.reviews().then(setReviews).catch((err) => setReviews({ entries: [], pending: 0, error: String(err) }))
  useEffect(() => {
    loadReviews()
    return window.api.triggers.on((t) => t.topic === 'quarantine' && loadReviews())
  }, [])

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

  // Load readiness plans and profiles when view switches to readiness
  useEffect(() => {
    if (view !== 'readiness') return
    setReadinessLoading(true)
    Promise.all([window.api.health.readiness(), window.api.profiles.list()])
      .then(([plans, profsList]) => {
        setReadiness(plans)
        setProfiles(profsList)
      })
      .catch(() => {
        setReadiness([])
        setProfiles([])
      })
      .finally(() => setReadinessLoading(false))
  }, [view])

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

  // marvin#691: rebuild the code graph, then show the re-run check in place (green on success, the error on failure)
  async function handleRebuildGraph() {
    const r = await window.api.health.rebuildGraph()
    if (r?.status) {
      setStatus(r.status)
      const fresh = r.status.checks?.find((c) => c.id === selected?.id)
      if (fresh) setSelected(fresh)
    }
    return r
  }

  async function reloadReadinessAndProfiles() {
    const [plans, profsList] = await Promise.all([window.api.health.readiness(), window.api.profiles.list()])
    setReadiness(plans)
    setProfiles(profsList)
  }

  if (error) {
    return <div className="flex h-full items-center justify-center text-red-400">Failed to load health status: {error}</div>
  }
  if (!status) {
    return <div className="flex h-full items-center justify-center text-neutral-500">Loading…</div>
  }

  if (selected) {
    return <HealthDrilldown check={selected} onBack={() => setSelected(null)} onRebuildGraph={handleRebuildGraph} />
  }

  const cov = status.coverage
  const agentProblems = agents?.filter((a) => ['failed', 'crashed', 'stopped'].includes(a.status)).length || 0
  const agentsRunning = agents?.filter((a) => a.status === 'running').length || 0
  return (
    <div className="p-6">
      <div className="mb-4 flex flex-wrap gap-1">
        {[['checks', 'Checks'], ['agents', 'Autonomous agents'], ['readiness', 'Project readiness'], ['reviews', reviews ? `Safety reviews (${reviews.pending})` : 'Safety reviews']].map(([id, label]) => (
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
      {view === 'reviews' ? (
        <SafetyReviews data={reviews} reload={loadReviews} />
      ) : view === 'agents' ? (
        <AgentsPanel agents={agents} />
      ) : view === 'readiness' ? (
        <ProjectReadinessPanel plans={readiness} profiles={profiles} loading={readinessLoading} onChanged={reloadReadinessAndProfiles} />
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
      <RecentErrors errors={status.recent_errors} />
      </>
      )}
    </div>
  )
}
