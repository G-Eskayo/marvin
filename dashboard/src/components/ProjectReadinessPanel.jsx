import { useEffect, useState } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'

const SEVERITY_COLOR = {
  ok: { bg: 'bg-emerald-950', border: 'border-emerald-900', dot: 'bg-emerald-500', text: 'text-emerald-300' },
  missing: { bg: 'bg-red-950', border: 'border-red-900', dot: 'bg-red-500', text: 'text-red-300' },
  'needs-human': { bg: 'bg-amber-950', border: 'border-amber-900', dot: 'bg-amber-500', text: 'text-amber-300' },
  unplanned: { bg: 'bg-neutral-900', border: 'border-neutral-700', dot: 'bg-neutral-600', text: 'text-neutral-400' }
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

function HealthSwitch({ plan, profiles, onReload }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const profile = profiles?.find((p) => p.repo === plan.repo)
  const dispatchOn = profile?.dispatch === 'on'
  const mergeOn = profile?.mergeFromDashboard === true

  async function handleDispatch() {
    setBusy(true)
    setError(null)
    try {
      const result = await window.api.profiles.setDispatch(plan.repo, dispatchOn ? 'off' : 'on')
      if (result.done) await onReload()
    } catch (e) {
      setError(cleanIpcError(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleMergeFromDashboard() {
    setBusy(true)
    setError(null)
    try {
      const result = await window.api.profiles.setMergeFromDashboard(plan.repo, !mergeOn)
      if (result.done) await onReload()
    } catch (e) {
      setError(cleanIpcError(e))
    } finally {
      setBusy(false)
    }
  }

  const canDispatch = plan.offers?.dispatch === true
  const canMerge = plan.offers?.merge_from_dashboard === true

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <button
        onClick={handleMergeFromDashboard}
        disabled={!canMerge || mergeOn || busy}
        className={`rounded px-2 py-1 text-xs disabled:opacity-50 ${mergeOn ? 'border border-neutral-700 text-neutral-300' : 'bg-sky-600 text-white hover:bg-sky-500'}`}
        title={!canMerge ? 'Project baseline must pass first' : mergeOn ? 'Already enabled' : 'Turn on'}
      >
        {mergeOn ? 'Merge from dashboard: on' : 'Turn on merge-from-dashboard…'}
      </button>
      <button
        onClick={handleDispatch}
        disabled={!canDispatch || dispatchOn || busy}
        className={`rounded px-2 py-1 text-xs disabled:opacity-50 ${dispatchOn ? 'border border-neutral-700 text-neutral-300' : 'bg-emerald-600 text-white hover:bg-emerald-500'}`}
        title={!canDispatch ? 'Project baseline must pass first' : dispatchOn ? 'Already enabled' : 'Turn on'}
      >
        {dispatchOn ? 'Dispatch: on' : 'Turn on dispatch…'}
      </button>
    </div>
  )
}

export default function ProjectReadinessPanel({ plans, loading }) {
  const [profiles, setProfiles] = useState(undefined)

  useEffect(() => {
    const loadProfiles = () => window.api.profiles.list().then(setProfiles).catch(() => setProfiles([]))
    loadProfiles()
  }, [])

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

  const handleReload = () => window.api.profiles.list().then(setProfiles).catch(() => setProfiles([]))

  return (
    <div className="space-y-4">
      <p className="text-xs text-neutral-500">
        Project readiness: one row per registered project, one chip per setup piece. Click a chip to see the reason.
      </p>
      <div className="space-y-3">
        {plans.map((plan) => {
          const repoName = plan.repo.split('/')[1]
          const isPlanned = plan.status === 'planned'

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
                <div className="flex flex-wrap gap-2">
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
                <div className="flex flex-wrap gap-2 opacity-50">
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
              {isPlanned && <HealthSwitch plan={plan} profiles={profiles} onReload={handleReload} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
