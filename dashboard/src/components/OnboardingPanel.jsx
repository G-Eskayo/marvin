import { useState } from 'react'

const SEVERITY_COLOR = {
  ok: { dot: 'bg-emerald-500', bg: 'bg-emerald-950', border: 'border-emerald-900', text: 'text-emerald-300' },
  'needs-human': { dot: 'bg-amber-500', bg: 'bg-amber-950', border: 'border-amber-900', text: 'text-amber-300' },
  missing: { dot: 'bg-red-500', bg: 'bg-red-950', border: 'border-red-900', text: 'text-red-300' },
  unmonitored: { dot: 'bg-neutral-600', bg: 'bg-neutral-900', border: 'border-neutral-700', text: 'text-neutral-400' }
}

function stalenessOpacity(generatedAt) {
  if (!generatedAt) return 0.35
  const STALE_AFTER_MS = 30 * 60 * 1000
  const ageMs = Date.now() - new Date(generatedAt).getTime()
  if (ageMs <= STALE_AFTER_MS) return 1
  const fadeRange = STALE_AFTER_MS * 3
  const fraction = Math.min(1, (ageMs - STALE_AFTER_MS) / fadeRange)
  return 1 - fraction * 0.65
}

function getHighestSeverity(pieces) {
  if (Object.values(pieces).some(p => p.state === 'missing')) return 'missing'
  if (Object.values(pieces).some(p => p.state === 'needs-human')) return 'needs-human'
  return 'ok'
}

function ProjectRow({ repo, name, pieces, generatedAt, onExpand }) {
  if (!pieces) {
    const colors = SEVERITY_COLOR.unmonitored
    return (
      <div style={{ opacity: 0.6 }} className={`flex flex-col gap-2 rounded-lg border border-dashed ${colors.border} ${colors.bg} p-4`}>
        <div className="flex items-center gap-3">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${colors.dot}`} />
          <h3 className="text-sm font-medium text-neutral-300">{name || repo.split('/')[1]}</h3>
        </div>
        <p className="text-xs text-neutral-500">No readiness plan yet</p>
      </div>
    )
  }

  const severity = getHighestSeverity(pieces)
  const colors = SEVERITY_COLOR[severity] ?? SEVERITY_COLOR.unmonitored
  const opacity = stalenessOpacity(generatedAt)
  const pieceCount = Object.keys(pieces).length

  return (
    <button
      onClick={onExpand}
      style={{ opacity }}
      className={`flex flex-col gap-2 rounded-lg border ${colors.border} ${colors.bg} p-4 text-left transition-opacity hover:opacity-100`}
    >
      <div className="flex items-center gap-3">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${colors.dot}`} />
        <h3 className="truncate text-sm font-medium text-white">{name || repo.split('/')[1]}</h3>
      </div>
      <div className="flex items-center gap-2">
        {Object.entries(pieces).map(([name, info]) => {
          const c = SEVERITY_COLOR[info.state] ?? SEVERITY_COLOR.unmonitored
          return (
            <span
              key={name}
              title={`${name}: ${info.reason}`}
              className={`h-2 w-2 rounded-full ${c.dot}`}
            />
          )
        })}
      </div>
    </button>
  )
}

function DetailedView({ repo, name, pieces, generatedAt, onBack }) {
  const colors = SEVERITY_COLOR[getHighestSeverity(pieces)] ?? SEVERITY_COLOR.unmonitored
  const opacity = stalenessOpacity(generatedAt)
  return (
    <div style={{ opacity }}>
      <button onClick={onBack} className="mb-4 text-xs text-neutral-400 hover:text-neutral-300">
        ← Back
      </button>
      <div className={`rounded-lg border ${colors.border} ${colors.bg} p-4`}>
        <h2 className="mb-2 text-lg font-medium text-white">{name || repo.split('/')[1]}</h2>
        <p className="mb-4 text-xs text-neutral-500">
          {generatedAt && `Generated: ${new Date(generatedAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`}
        </p>
        <div className="space-y-2">
          {Object.entries(pieces).map(([pieceName, info]) => {
            const pieceColors = SEVERITY_COLOR[info.state] ?? SEVERITY_COLOR.unmonitored
            return (
              <div key={pieceName} className={`rounded border ${pieceColors.border} ${pieceColors.bg} p-3`}>
                <div className="mb-1 flex items-center gap-2">
                  <span className={`h-1.5 w-1.5 rounded-full ${pieceColors.dot}`} />
                  <span className="text-sm font-medium capitalize text-white">{pieceName.replace(/_/g, ' ')}</span>
                  <span className={`ml-auto text-xs ${pieceColors.text}`}>{info.state}</span>
                </div>
                <p className={`text-xs ${pieceColors.text}`}>{info.reason}</p>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default function OnboardingPanel({ plans = [] }) {
  const [expanded, setExpanded] = useState(null)

  if (plans.length === 0) {
    return <div className="text-center text-neutral-500">No projects registered yet</div>
  }

  if (expanded) {
    const plan = plans.find(p => p.repo === expanded)
    if (!plan) return null
    return (
      <DetailedView
        repo={plan.repo}
        name={null}
        pieces={plan.pieces}
        generatedAt={plan.generated_at}
        onBack={() => setExpanded(null)}
      />
    )
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      {plans.map((plan) => (
        <ProjectRow
          key={plan.repo}
          repo={plan.repo}
          name={null}
          pieces={plan.pieces}
          generatedAt={plan.generated_at}
          onExpand={() => setExpanded(plan.repo)}
        />
      ))}
    </div>
  )
}
