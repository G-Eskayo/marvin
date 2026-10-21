import { useEffect, useState } from 'react'
import { summarizeChecks, runningLine, formatClock, formatAgo, toMs } from '../lib/check_progress.js'

// A PR card's GitHub checks while they run (marvin#555, the design Gil approved 2026-10-21): a bar filling as checks
// finish, "N of M done", what is still running and for how long, and when GitHub was last asked. Clicking the bar opens
// one row per check (collapsed by default, like the app's other ▸ sections). Times tick every second from the start
// and finish times already fetched: no GitHub call. `now` is for tests; the app passes nothing and gets a live clock.
const ICON = { passed: '✓', failed: '✗', running: '◌', queued: '◌', skipped: '–', neutral: '–' }
const ICON_TONE = { passed: 'text-emerald-400', failed: 'text-red-400', running: 'text-amber-400', queued: 'text-neutral-500', skipped: 'text-neutral-500', neutral: 'text-neutral-500' }
const BAR_TONE = { wait: 'bg-amber-400', blocked: 'bg-red-400', ready: 'bg-emerald-400' }

function useNow(fixed) {
  const [now, setNow] = useState(() => fixed ?? Date.now())
  useEffect(() => {
    if (fixed != null) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [fixed])
  return fixed ?? now
}

export default function CheckProgress({ checks, tone = 'wait', now: fixedNow = null, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const now = useNow(fixedNow)
  const s = summarizeChecks(checks?.runs, now)
  if (!s.total) return null
  const line = runningLine(s)
  const checkedAt = toMs(checks?.checkedAt)
  const ago = checkedAt == null ? null : formatAgo(now - checkedAt)
  return (
    <div className="w-72 max-w-xs text-xs" data-check-progress>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        title={open ? 'Hide each check' : 'Show each check'}
        className="w-full text-right text-neutral-400 hover:text-neutral-200"
      >
        <span className="flex items-center gap-2">
          <span className="h-1.5 flex-1 overflow-hidden rounded-sm bg-neutral-800">
            <span className={`block h-full transition-[width] ${BAR_TONE[tone] || BAR_TONE.wait}`} style={{ width: `${s.percent}%` }} />
          </span>
          <span className="shrink-0 text-neutral-300">{open ? '▾' : '▸'} {s.done} of {s.total} done</span>
        </span>
        {line && <span className="mt-1 block truncate" title={line}>Still running: {line}</span>}
      </button>
      {open && (
        <table className="mt-1 w-full table-fixed text-left">
          <tbody>
            {s.rows.map((r, i) => (
              <tr key={`${r.name}-${i}`} data-check-row={r.status}>
                <td className={`w-4 py-0.5 align-top ${ICON_TONE[r.status] || 'text-neutral-500'}`}>{ICON[r.status] || '·'}</td>
                <td className="truncate py-0.5 pr-2 text-neutral-300" title={r.name}>{r.name}</td>
                <td className="w-14 py-0.5 text-neutral-500">{r.label}</td>
                <td className="w-12 py-0.5 text-right font-mono text-neutral-400">{formatClock(r.time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {ago && <p className="mt-1 text-right text-neutral-500">Last checked {ago}</p>}
    </div>
  )
}
