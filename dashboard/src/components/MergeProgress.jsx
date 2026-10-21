import CheckProgress from './CheckProgress.jsx'
import { mergeRuns, estimateLine, busyLine } from '../lib/merge_progress.js'

// A PR's merge, stage by stage (marvin#568): #557's CheckProgress, unchanged, fed one row per stage (Queued → Fetching
// PR → Rebasing on main → Installing → Tests → Merging on GitHub → After-merge checks → Done). The rows come from the
// stage events the webhook pushes; times tick from their start times, so nothing is asked again. Under the bar: the
// usual duration from real past merges and which Mac runs it, and a plain warning when that Mac is busy.
const TONE = { failed: 'blocked', merged: 'ready' }

export default function MergeProgress({ progress, now = null, defaultOpen = false }) {
  if (!progress) return null
  const estimate = estimateLine(progress)
  const busy = busyLine(progress)
  return (
    <div className="flex flex-col items-end" data-merge-progress={progress.outcome || 'running'}>
      <CheckProgress checks={{ runs: mergeRuns(progress) }} tone={TONE[progress.outcome] || 'wait'} now={now} defaultOpen={defaultOpen} />
      {estimate && <p className="mt-1 w-72 max-w-xs text-right text-xs text-neutral-500">{estimate}</p>}
      {busy && <p className="mt-1 w-72 max-w-xs text-right text-xs text-amber-400" data-merge-busy>{busy}</p>}
    </div>
  )
}
