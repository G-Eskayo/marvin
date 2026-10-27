import { useEffect, useState } from 'react'
import { arrowOf, statusLabel, shortGoal, clip, UNMEASURED } from '../lib/project_goals.js'

// Project goals (Gil, 2026-10-26, layouts approved in chat): the goal and its signals at the top of each board, and
// one row per active project in Activity (marvin#625's progress strip). Every text is rendered as text (React escapes
// it); nothing here sets HTML. No signal is measured yet, so each value is "—" with "not measured yet".

const CHIP = 'rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-300'

// The profiles' goals, read once and again when a profile changes (the 'goals' trigger). No polling.
export function useGoals() {
  const [goals, setGoals] = useState(null)
  useEffect(() => {
    const load = () => window.api.profiles.goals().then(setGoals).catch(() => setGoals([]))
    load()
    return window.api.triggers.on((t) => t.topic === 'goals' && load())
  }, [])
  return goals
}

const signalLabel = (s) => [s.name, arrowOf(s.better)].filter(Boolean).join(' ')

export function GoalHeader({ goal }) {
  if (!goal) return null
  if (!goal.goal) {
    const label = statusLabel(goal.status)
    return label ? <p className="mb-3 text-sm text-neutral-500">{label}</p> : null
  }
  return (
    <div className="mb-3 min-w-0">
      <p className="break-words text-sm text-neutral-300">
        <span className="text-neutral-500">Goal:</span> {goal.goal}
      </p>
      {goal.signals.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {goal.signals.map((s, i) => (
            <span key={i} className={CHIP} title={UNMEASURED.title}>
              {signalLabel(s)} <span className="ml-1 text-neutral-500">{UNMEASURED.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function stateOf(r) {
  const { held, total } = r.stuck
  if (total > 0) return { text: held === total ? 'held' : `stuck ${total}`, tone: 'text-amber-300' }
  if (r.mergedWeek > 0) return { text: 'moving', tone: 'text-emerald-300' }
  return { text: '—', tone: 'text-neutral-600' }
}

function Row({ r, onOpen }) {
  const st = stateOf(r)
  const label = statusLabel(r.status)
  const cells = (
    <>
      <span className="min-w-0 truncate text-sm text-white">{r.name}</span>
      <span className="min-w-0">
        <span className="block truncate text-xs text-neutral-300" title={r.goal || undefined}>
          {r.goal ? shortGoal(r.goal) : label || '—'}
        </span>
        {r.signals.length > 0 && (
          <span className="block truncate text-[11px] text-neutral-500">
            {r.signals.map((s, i) => (
              <span key={i} className="mr-2" title={`${s.name}: ${UNMEASURED.title}`}>
                {clip(s.name, 15)} {UNMEASURED.value}
              </span>
            ))}
          </span>
        )}
      </span>
      <span className="text-right text-xs">
        <span className={`block ${st.tone}`}>{st.text}</span>
        {r.mergedWeek > 0 && <span className="block text-[11px] text-neutral-500">{r.mergedWeek} PRs/wk</span>}
      </span>
    </>
  )
  const grid = 'grid w-full grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto] items-start gap-3 border-b border-neutral-800 px-3 py-2 text-left last:border-b-0'
  return r.hasBoard ? (
    <button onClick={() => onOpen?.(r.repo)} className={`${grid} hover:bg-neutral-800/50`}>
      {cells}
    </button>
  ) : (
    <div className={grid}>{cells}</div>
  )
}

export function ProjectsProgress({ active = [], rest = [], onOpen, initiallyExpanded = false }) {
  const [open, setOpen] = useState(initiallyExpanded)
  if (active.length === 0 && rest.length === 0) return null
  return (
    <div className="mx-6 mb-4 min-w-0">
      <h2 className="mb-2 text-sm text-neutral-500">Projects</h2>
      <div className="overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900">
        {active.map((r) => (
          <Row key={r.repo} r={r} onOpen={onOpen} />
        ))}
        {rest.length > 0 && (
          <>
            <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-neutral-500 hover:text-neutral-300">
              <span>{open ? '▾' : '▸'}</span>
              <span>{rest.length} parked or done</span>
            </button>
            {open && (
              <div className="opacity-60">
                {rest.map((r) => (
                  <Row key={r.repo} r={r} onOpen={onOpen} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// Activity ▸ Projects: reads the rows from the main process and re-reads them when goals, boards or PRs change.
export default function ProjectsProgressView({ onOpen }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    const load = () => window.api.activity.progress().then(setData).catch(() => {})
    load()
    return window.api.triggers.on((t) => (t.topic === 'goals' || t.topic === 'activity' || t.topic === 'mr') && load())
  }, [])
  return data ? <ProjectsProgress active={data.active} rest={data.rest} onOpen={onOpen} /> : null
}
