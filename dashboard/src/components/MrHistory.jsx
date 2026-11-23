import { useEffect, useMemo, useState } from 'react'
import { groupByDay, pageOf, filterRows, openDuration, notesLine } from '../lib/mr_history_view.js'
import { revertedBy } from '../lib/merge_motion.js'
import { useMergeMotion, MotionSlot } from './MergeMotion.jsx'

// MR Review's Merged view (marvin#419): every merged PR across projects, open PRs with refusal notes, and dropped PRs
// newest first, grouped by day, 5 days per page. Draws the saved history at once, then a fresh read replaces it.
const BY_LABEL = { you: 'you', auto: 'auto-merge', unrecorded: 'not recorded' }
const rowKey = (r) => `${r.kind}|${r.url}|${r.at}`
const FILTERS = ["All", "Merged", "Still open", "Dropped"]

function age(at, now = Date.now()) {
  if (!at) return ''
  const s = Math.max(0, (now - at) / 1000)
  if (s < 60) return 'updated just now'
  if (s < 3600) return `updated ${Math.floor(s / 60)} min ago`
  if (s < 86400) return `updated ${Math.floor(s / 3600)} h ago`
  return `updated ${Math.floor(s / 86400)} days ago`
}

export function HistoryRow({ row, onOpen, reverted = null }) {
  const time = Number.isNaN(Date.parse(row.at)) ? '' : new Date(row.at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  const statusIcon = row.kind === 'merged' ? '✓' : row.kind === 'open' ? '⏳' : '✗'
  const statusColor = row.kind === 'merged' ? 'text-emerald-400' : row.kind === 'open' ? 'text-amber-400' : 'text-red-400'
  const trailing = row.kind === 'merged' ? BY_LABEL[row.by] || row.by : row.kind === 'open' ? notesLine(row.notes) : 'dropped'
  const trailingColor = row.kind === 'merged' ? 'text-neutral-400' : row.kind === 'open' ? 'text-amber-300' : 'text-neutral-500'

  return (
    <button onClick={() => onOpen(row)} data-kind={row.kind}
      className="grid w-full grid-cols-[1.25rem_1fr_auto_auto_auto] items-baseline gap-3 rounded px-2 py-1.5 text-left text-sm hover:bg-neutral-800/60">
      <span className={statusColor}>{statusIcon}</span>
      <span className="truncate text-neutral-200"><span className="font-mono text-neutral-400">#{row.number}</span> {row.title}{reverted != null && <span data-reverted-by={reverted} className="ml-2 rounded-full border border-neutral-700 px-1.5 py-px text-[11px] text-neutral-400">reverted by #{reverted}</span>}</span>
      <span className="text-xs text-neutral-500">{(row.repo || '').split('/')[1]}</span>
      <span className="text-xs tabular-nums text-neutral-500">{row.kind === 'open' ? openDuration(row.at) : time}</span>
      <span className={`text-xs ${trailingColor}`}>{trailing}</span>
    </button>
  )
}

// `motion` (the Merged view’s useMergeMotion): a merge arriving while you look sweeps its row in, left to right.
export function HistoryList({ data, page, setPage, onOpen, now, motion = null, filter = "All", setFilter = null }) {
  const allRows = motion ? motion.shown : data.rows
  const rows = filterRows(allRows, filter)
  const reverts = useMemo(() => revertedBy(rows), [rows])
  const days = groupByDay(rows, now)
  const view = pageOf(days, page)
  if (!allRows.length) return <p className="text-sm text-neutral-500">{data.updatedAt ? "Nothing merged or refused yet." : "Reading merge history…"}</p>
  return (
    <div>
      {setFilter && (
        <div className="mb-3 flex gap-2">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => { setFilter(f); setPage(0) }}
              className={`rounded px-3 py-1 text-xs font-medium ${
                f === filter
                  ? "bg-neutral-700 text-neutral-100"
                  : "bg-neutral-900 text-neutral-400 hover:text-neutral-300"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      )}
      {!rows.length && filter !== "All" && (
        <p className="text-sm text-neutral-500">No {filter.toLowerCase()} items.</p>
      )}
      {rows.length > 0 && (
        <>
          {view.days.map((d) => (
            <section key={d.key} className="mb-4">
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-500">{d.label}</h3>
              {d.rows.map((r) => {
                const row = <HistoryRow key={rowKey(r)} row={r} onOpen={onOpen} reverted={reverts[r.url] ?? null} />
                return motion ? <MotionSlot key={rowKey(r)} slotRef={motion.slotRef(rowKey(r))} waiting={motion.entering.has(rowKey(r))} pad={0}>{row}</MotionSlot> : row
              })}
            </section>
          ))}
          {view.pages > 1 && (
            <div className="flex items-center gap-2 text-xs text-neutral-400">
              <button disabled={view.page === 0} onClick={() => setPage(view.page - 1)} className="rounded bg-neutral-900 px-2 py-1 disabled:opacity-40">← Newer</button>
              <span>Page {view.page + 1} of {view.pages}</span>
              <button disabled={view.page >= view.pages - 1} onClick={() => setPage(view.page + 1)} className="rounded bg-neutral-900 px-2 py-1 disabled:opacity-40">Older →</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default function MrHistory({ onOpen }) {
  const [data, setData] = useState({ rows: [], updatedAt: null, errors: [] })
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(0)
  const [filter, setFilter] = useState("All")
  // Rows that arrive after the first fresh read sweep in (#838); the first read’s new rows merged while you were away,
  // so they just show (the result, not the motion).
  const [firstReadDone, setFirstReadDone] = useState(false)

  function refresh() {
    setLoading(true)
    window.api.mr.history({ fresh: true }).then(setData).catch((e) => setData((d) => ({ ...d, errors: [{ repo: "history", message: String(e) }] }))).finally(() => { setLoading(false); setFirstReadDone(true) })
  }
  useEffect(() => {
    window.api.mr.history({ fresh: false }).then((d) => d?.updatedAt && setData(d)).catch(() => {})
    refresh()
    // A merge GitHub confirms while this view is open arrives here: one fresh read per merge, pushed, never polled.
    return window.api.mr.onMergeEvent?.((url, op) => { if (op?.state === "merged") refresh() })
  }, [])
  const motion = useMergeMotion(data.updatedAt ? data.rows : null, { keyOf: rowKey, visible: page === 0, chips: false, animateChanges: firstReadDone })

  return (
    <div>
      <div className="mb-3 flex items-center gap-3 text-xs text-neutral-500">
        <span>Merged PRs, open PRs with refusals, and dropped PRs across every project. Click one for its detail.</span>
        <span className="ml-auto">{loading ? "updating…" : age(data.updatedAt)}</span>
        <button onClick={refresh} disabled={loading} className="rounded bg-neutral-900 px-2 py-1 text-neutral-400 hover:text-neutral-200 disabled:opacity-50">Refresh</button>
      </div>
      {data.errors?.length > 0 && <p className="mb-2 text-xs text-amber-300">Couldn’t read: {data.errors.map((e) => `${e.repo} (${e.message})`).join("; ")}. Showing what could be read.</p>}
      <HistoryList data={data} page={page} setPage={setPage} onOpen={onOpen} motion={motion} filter={filter} setFilter={setFilter} />
    </div>
  )
}
