import { useState } from 'react'

const SEVERITY_COLOR = {
  ok: { bg: 'bg-emerald-950', border: 'border-emerald-900', dot: 'bg-emerald-500', text: 'text-emerald-300' },
  missing: { bg: 'bg-red-950', border: 'border-red-900', dot: 'bg-red-500', text: 'text-red-300' },
  'needs-human': { bg: 'bg-amber-950', border: 'border-amber-900', dot: 'bg-amber-500', text: 'text-amber-300' },
  unplanned: { bg: 'bg-neutral-900', border: 'border-neutral-700', dot: 'bg-neutral-600', text: 'text-neutral-400' }
}

function ControlButton({ enabled, label, onClick, loading }) {
  return (
    <button
      disabled={!enabled || loading}
      onClick={onClick}
      className="rounded px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      style={enabled ? { borderColor: 'rgb(115, 115, 115)', backgroundColor: 'rgb(23, 23, 23)', color: 'rgb(212, 212, 212)' } : { borderColor: 'rgb(82, 82, 82)', backgroundColor: 'rgb(31, 31, 31)', color: 'rgb(120, 113, 108)' }}
      title={!enabled ? 'Available once the baseline passes' : ''}
    >
      {loading ? 'Saving…' : label}
    </button>
  )
}

function PieceChip({ name, state, reason }) {
  const colors = SEVERITY_COLOR[state] || SEVERITY_COLOR.unplanned
  const [expanded, setExpanded] = useState(false)

  const display = {
    ok: '✓',
    missing: '✗',
    'needs-human': '!',
    unplanned: '?'
  }[state] || '?'

  return (
    <div
      onClick={() => setExpanded(!expanded)}
      className={`cursor-pointer rounded border ${colors.border} ${colors.bg} px-2 py-1 text-xs font-medium transition-all hover:opacity-90`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${colors.dot} align-text-top mr-1`} />
      <span className={colors.text}>{name}</span>
      {expanded && reason && (
        <div className="mt-2 border-t border-current pt-2 text-left text-neutral-300">
          {reason}
        </div>
      )}
    </div>
  )
}

export default function ProjectReadinessPanel({ plans, profiles, loading, reload }) {
  const [loadingStates, setLoadingStates] = useState({})

  if (loading) {
    return <div className="flex h-64 items-center justify-center text-neutral-500">Loading project readiness…</div>
  }

  if (!plans || plans.length === 0) {
    return <div className="flex h-64 items-center justify-center text-neutral-500">No projects registered yet</div>
  }

  const pieces = [
    'profile',
    'stack',
    'test_command',
    'ci',
    'triage_labels',
    'agent_docs',
    'board',
    'clone_and_toolchain',
    'generated_paths',
    'baseline'
  ]

  const getProfileFor = (repo) => profiles?.find((p) => p.repo === repo)

  const handleToggleMergeFromDashboard = async (repo, current) => {
    setLoadingStates((prev) => ({ ...prev, [`mfd-${repo}`]: true }))
    try {
      await window.api.profiles.setMergeFromDashboard(repo, !current)
      await reload?.()
    } finally {
      setLoadingStates((prev) => ({ ...prev, [`mfd-${repo}`]: false }))
    }
  }

  const handleToggleDispatch = async (repo, current) => {
    setLoadingStates((prev) => ({ ...prev, [`dispatch-${repo}`]: true }))
    try {
      await window.api.profiles.setDispatch(repo, current === 'on' ? 'off' : 'on')
      await reload?.()
    } finally {
      setLoadingStates((prev) => ({ ...prev, [`dispatch-${repo}`]: false }))
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-neutral-500">
        Project readiness: one row per registered project, one chip per setup piece. Click a chip to see the reason.
      </p>
      <div className="space-y-3">
        {plans.map((plan) => {
          const repoName = plan.repo.split('/')[1]
          const isPlanned = plan.status === 'planned'
          const profile = getProfileFor(plan.repo)
          const canMergeFromDashboard = plan.offers?.merge_from_dashboard === true
          const canDispatch = plan.offers?.dispatch === true
          const isMergeFromDashboardOn = profile?.mergeFromDashboard === true
          const isDispatchOn = profile?.dispatch === 'on'

          return (
            <div key={plan.repo} className="rounded-lg border border-neutral-800 bg-neutral-950 p-4">
              <div className="mb-3">
                <h3 className="text-sm font-medium text-white">{repoName}</h3>
                {isPlanned && plan.generated_at && (
                  <p className="text-xs text-neutral-500">
                    Scanned: {new Date(plan.generated_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
                  </p>
                )}
                {!isPlanned && (
                  <p className="text-xs text-neutral-500">
                    {plan.status === 'not_planned_yet' ? 'Not scanned yet' : 'Read error'}
                  </p>
                )}
              </div>
              {isPlanned && plan.pieces ? (
                <div className="flex flex-wrap gap-2 mb-3">
                  {pieces.map((piece) => {
                    const piece_info = plan.pieces[piece]
                    const state = piece_info?.state || 'unplanned'
                    const reason = piece_info?.reason || ''
                    return (
                      <PieceChip
                        key={piece}
                        name={piece.replace(/_/g, ' ')}
                        state={state}
                        reason={reason}
                      />
                    )
                  })}
                </div>
              ) : (
                <div className="flex flex-wrap gap-2 opacity-50 mb-3">
                  {pieces.map((piece) => (
                    <PieceChip
                      key={piece}
                      name={piece.replace(/_/g, ' ')}
                      state="unplanned"
                      reason=""
                    />
                  ))}
                </div>
              )}
              {isPlanned && (
                <div className="flex gap-2 border-t border-neutral-700 pt-3">
                  <ControlButton
                    enabled={canMergeFromDashboard}
                    label={isMergeFromDashboardOn ? 'Turn off merge from dashboard' : 'Turn on merge from dashboard'}
                    onClick={() => handleToggleMergeFromDashboard(plan.repo, isMergeFromDashboardOn)}
                    loading={loadingStates[`mfd-${plan.repo}`]}
                  />
                  <ControlButton
                    enabled={canDispatch}
                    label={isDispatchOn ? 'Turn off dispatch' : 'Turn on dispatch'}
                    onClick={() => handleToggleDispatch(plan.repo, isDispatchOn)}
                    loading={loadingStates[`dispatch-${plan.repo}`]}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
