import { useEffect, useMemo, useState } from 'react'
import { groupByDay, pageOf, filterRows } from '../lib/mr_history_view.js'
import { revertedBy } from '../lib/merge_motion.js'
import { useMergeMotion, MotionSlot } from './MergeMotion.jsx'

// MR Review's Merged view (marvin#419): every merged PR across projects and every refused Approve, newest first,
// grouped by day, 5 days per page. Draws the saved history at once, then a fresh read replaces it.
const BY_LABEL = { you: "you", auto: "auto-merge", unrecorded: "not recorded" }
const KIND_LABELS = { all: "All", merged: "Merged", open: "Still open", dropped: "Dropped" }
const rowKey = (r) => `${r.kind}|${r.url}|${r.at}`

function age(at, now = Date.now()) {
  if (!at) return ""
  const s = Math.max(0, (now - at) / 1000)
  if (s < 60) return "updated just now"
  if (s < 3600) return `updated ${Math.floor(s / 60)} min ago`
  if (s < 86400) return `updated ${Math.floor(s / 3600)} h ago`
  return `updated ${Math.floor(s / 86400)} days ago`
}

export function HistoryRow({ row, onOpen, reverted = null }) {
  const time = Number.isNaN(Date.parse(row.at)) ? "" : new Date(row.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
  const isMerged = row.kind === "merged"
  const isOpen = row.kind === "open"
  const isDropped = row.kind === "dropped"
  const iconColor = isMerged ? "text-emerald-400" : isOpen ? "text-amber-400" : "text-red-400"
  const icon = isMerged ? "✓" : isOpen ? "⌛" : "✗"
  const statusColor = isMerged ? "text-neutral-400" : isOpen ? "text-amber-300" : "text-red-300"
  const statusLabel = isMerged ? (BY_LABEL[row.by] || row.by) : isOpen ? `refused: ${row.plainReason}` : "dropped"

  return (
    <div className="rounded px-2 py-1.5">
      <button onClick={() => onOpen(row)} data-kind={row.kind}
        className="grid w-full grid-cols-[1.25rem_1fr_auto_auto_auto] items-baseline gap-3 text-left text-sm hover:bg-neutral-800/60 rounded px-2 py-1.5">
        <span className={iconColor}>{icon}</span>
        <span className="truncate text-neutral-200"><span className="font-mono text-neutral-400">#{row.number}</span> {row.title}{reverted != null && <span data-reverted-by={reverted} className="ml-2 rounded-full border border-neutral-700 px-1.5 py-px text-[11px] text-neutral-400">reverted by #{reverted}</span>}</span>
        <span className="text-xs text-neutral-500">{(row.repo || "").split("/")[1]}</span>
        <span className="text-xs tabular-nums text-neutral-500">{time}</span>
        <span className={`text-xs ${statusColor}`}>{statusLabel}</span>
      </button>
      {isOpen && row.notes && row.notes.length > 0 && (
        <div className="mt-1 text-xs text-neutral-400 ml-6">
          <p className="text-amber-300/70">Refused {row.refusalCount > 1 ? `${row.refusalCount} times` : "once"}:</p>
          <ul className="ml-2 list-disc">
            {row.notes.map((n, i) => (
              <li key={i} className="text-neutral-500">{n.reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// `motion` (the Merged view's useMergeMotion): a merge arriving while you look sweeps its row in, left to right.
export function HistoryList({ data, page, setPage, onOpen, now, motion = null, filter = "all", setFilter = null }) {
  const rows = motion ? motion.shown : data.rows
  const filtered = useMemo(() => filterRows(rows, filter), [rows, filter])
  const reverts = useMemo(() => revertedBy(filtered), [filtered])
  const days = groupByDay(filtered, now)
  const view = pageOf(days, page)
  if (!rows.length) return <p className="text-sm text-neutral-500">{data.updatedAt ? "Nothing merged or refused yet." : "Reading merge history…"}</p>
  return (
    <div>
      {setFilter && (
        <div className="mb-4 flex gap-2">
          {Object.entries(KIND_LABELS).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={`text-xs rounded px-3 py-1 ${filter === k ? "bg-blue-900 text-blue-200" : "bg-neutral-800 text-neutral-400 hover:bg-neutral-700"}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {filtered.length === 0 ? (
        <p className="text-sm text-neutral-500">Nothing in this filter.</p>
      ) : (
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
  const [filter, setFilter] = useState("all")
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
        <span>Merged PRs across every project, every refusal, and every dropped PR. Click one for its detail.</span>
        <span className="ml-auto">{loading ? "updating…" : age(data.updatedAt)}</span>
        <button onClick={refresh} disabled={loading} className="rounded bg-neutral-900 px-2 py-1 text-neutral-400 hover:text-neutral-200 disabled:opacity-50">Refresh</button>
      </div>
      {data.errors?.length > 0 && <p className="mb-2 text-xs text-amber-300">Couldn’t read: {data.errors.map((e) => `${e.repo} (${e.message})`).join("; ")}. Showing what could be read.</p>}
      <HistoryList data={data} page={page} setPage={setPage} onOpen={onOpen} motion={motion} filter={filter} setFilter={setFilter} />
    </div>
  )
}
