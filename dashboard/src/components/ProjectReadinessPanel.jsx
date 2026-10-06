import { useEffect, useState } from 'react'

const SEVERITY_COLOR = {
  red: { bg: 'bg-red-950', border: 'border-red-900', dot: 'bg-red-500', text: 'text-red-300' },
  yellow: { bg: 'bg-amber-950', border: 'border-amber-900', dot: 'bg-amber-500', text: 'text-amber-300' },
  green: { bg: 'bg-emerald-950', border: 'border-emerald-900', dot: 'bg-emerald-500', text: 'text-emerald-300' },
  gray: { bg: 'bg-neutral-900', border: 'border-neutral-700', dot: 'bg-neutral-600', text: 'text-neutral-400' }
}

function getPieceState(state) {
  if (state === 'ok') return 'green'
  if (state === 'needs-human') return 'yellow'
  if (state === 'missing') return 'red'
  return 'gray'
}

function PieceRow({ name, state, reason }) {
  const colors = SEVERITY_COLOR[getPieceState(state)]
  return (
    <div className="flex items-start gap-2 py-2">
      <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${colors.dot}`} />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-white">{name}</div>
        {reason && <div className={`text-xs ${colors.text}`}>{reason}</div>}
      </div>
      <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${colors.bg} ${colors.text}`}>
        {state}
      </span>
    </div>
  )
}

function ProjectCard({ project, onClick }) {
  const worstColor = project.error
    ? SEVERITY_COLOR.red
    : SEVERITY_COLOR[project.worstState === 'ok' ? 'green' : project.worstState === 'needs-human' ? 'yellow' : 'red']

  const pieces = project.pieces || {}
  const pieceCount = Object.keys(pieces).length
  const okCount = Object.values(pieces).filter(p => p.state === 'ok').length

  return (
    <button
      onClick={onClick}
      className={`flex flex-col gap-2 rounded-lg border ${worstColor.border} ${worstColor.bg} p-4 text-left transition-opacity hover:opacity-100`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${worstColor.dot}`} />
          <h3 className="truncate text-sm font-medium text-white">{project.name}</h3>
        </div>
        {!project.error && pieceCount > 0 && (
          <span className="shrink-0 text-xs text-neutral-400">
            {okCount}/{pieceCount} ready
          </span>
        )}
      </div>
      {project.error ? (
        <p className={`text-xs ${worstColor.text}`}>Error: {project.error}</p>
      ) : (
        <p className={`line-clamp-2 text-xs ${worstColor.text}`}>
          {project.generatedAt ? `Updated ${new Date(project.generatedAt).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })}` : 'Pending first scan'}
        </p>
      )}
    </button>
  )
}

function ProjectDetailModal({ project, onBack }) {
  return (
    <div className="p-6">
      <button
        onClick={onBack}
        className="mb-4 text-sm text-blue-400 hover:text-blue-300"
      >
        ← Back
      </button>
      <h2 className="mb-4 text-lg font-semibold text-white">{project.name}</h2>
      <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
        {project.error ? (
          <p className="text-sm text-red-300">Error: {project.error}</p>
        ) : Object.keys(project.pieces || {}).length === 0 ? (
          <p className="text-sm text-neutral-400">No readiness data available yet</p>
        ) : (
          <div className="space-y-1">
            {Object.entries(project.pieces || {}).map(([key, piece]) => (
              <PieceRow key={key} name={key} state={piece.state} reason={piece.reason} />
            ))}
          </div>
        )}
        {project.generatedAt && (
          <p className="mt-4 text-xs text-neutral-500">
            Generated: {new Date(project.generatedAt).toLocaleString()}
          </p>
        )}
      </div>
    </div>
  )
}

export default function ProjectReadinessPanel() {
  const [projects, setProjects] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    const load = () => {
      window.api.health
        .readiness()
        .then(result => {
          setProjects(result || [])
          setError(null)
        })
        .catch(err => {
          setError(String(err))
        })
    }

    load()
    const interval = setInterval(load, 60_000)
    return () => clearInterval(interval)
  }, [])

  if (error) {
    return <div className="flex h-full items-center justify-center text-red-400">Failed to load project readiness: {error}</div>
  }
  if (projects === null) {
    return <div className="flex h-full items-center justify-center text-neutral-500">Loading…</div>
  }

  if (selected) {
    return <ProjectDetailModal project={selected} onBack={() => setSelected(null)} />
  }

  if (projects.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-center text-neutral-500">
        <p className="text-lg font-medium text-neutral-300">No projects yet</p>
        <p className="max-w-md text-sm">
          Fills in automatically after the next hourly scan — the ticket pipeline checks every project's onboarding readiness and stores the results here.
        </p>
      </div>
    )
  }

  const failingProjects = projects.filter(p => p.error || p.worstState === 'missing')
  const needingHuman = projects.filter(p => !p.error && p.worstState === 'needs-human')
  const readyProjects = projects.filter(p => !p.error && p.worstState === 'ok')

  return (
    <div className="space-y-6">
      {failingProjects.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase text-red-400">Missing setup ({failingProjects.length})</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {failingProjects.map(p => (
              <ProjectCard key={p.repo} project={p} onClick={() => setSelected(p)} />
            ))}
          </div>
        </div>
      )}
      {needingHuman.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase text-amber-400">Needs attention ({needingHuman.length})</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {needingHuman.map(p => (
              <ProjectCard key={p.repo} project={p} onClick={() => setSelected(p)} />
            ))}
          </div>
        </div>
      )}
      {readyProjects.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase text-emerald-400">Ready ({readyProjects.length})</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {readyProjects.map(p => (
              <ProjectCard key={p.repo} project={p} onClick={() => setSelected(p)} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
