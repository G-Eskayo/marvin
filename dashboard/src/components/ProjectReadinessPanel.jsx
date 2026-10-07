import { useState } from 'react'
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

function ReadinessAction({ repo, label, offersKey, isOn, plan, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const canTurnOn = plan.offers?.[offersKey] === true
  const disabledReason = !canTurnOn && plan.pieces?.baseline?.reason ? `Reason: ${plan.pieces.baseline.reason}` : null

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      const handler = offersKey === 'dispatch' ? window.api.readiness.setDispatch : window.api.readiness.setMergeFromDashboard
      const value = offersKey === 'dispatch' ? 'on' : true
      await handler(repo, value)
      await onChanged?.()
    } catch (e) {
      setError(cleanIpcError(e))
    } finally {
      setBusy(false)
    }
  }

  if (isOn) return null

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={toggle}
        disabled={!canTurnOn || busy}
        title={disabledReason || ''}
        className={`rounded px-2 py-1 text-xs transition-colors ${
          canTurnOn ? 'bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50' : 'border border-neutral-700 text-neutral-400 bg-neutral-900 cursor-not-allowed opacity-50'
        }`}
      >
        {busy ? `Turning on…` : label}
      </button>
      {error && <p className="text-[10px] text-red-400">{error}</p>}
      {disabledReason && <p className="text-[10px] text-neutral-500">{disabledReason}</p>}
    </div>
  )
}

export default function ProjectReadinessPanel({ plans, loading, onChanged }) {
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

  return (
    <div className="space-y-4">
      <p className="text-xs text-neutral-500">
        Project readiness: one row per registered project, one chip per setup piece. Click a chip to see the reason.
      </p>
      <div className="space-y-3">
        {plans.map((plan) => {
          const repoName = plan.repo.split('/')[1]
          const isPlanned = plan.status === 'planned'
          const dispatchIsOn = plan.current?.dispatch === 'on'
          const mergeFromDashboardIsOn = plan.current?.mergeFromDashboard === true

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
              {isPlanned && (
                <div className="mt-4 flex gap-2">
                  <ReadinessAction
                    repo={plan.repo}
                    label="Turn on merge-from-dashboard"
                    offersKey="merge_from_dashboard"
                    isOn={mergeFromDashboardIsOn}
                    plan={plan}
                    onChanged={onChanged}
                  />
                  <ReadinessAction
                    repo={plan.repo}
                    label="Turn on dispatch"
                    offersKey="dispatch"
                    isOn={dispatchIsOn}
                    plan={plan}
                    onChanged={onChanged}
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
