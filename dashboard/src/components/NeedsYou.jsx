import { useEffect, useState } from 'react'
import { readSaved, writeSaved, ageText } from '../lib/saved_state.js'
import { readSort, writeSort, sortRows, paginate } from '../lib/needs_you_view.js'
import { cleanIpcError } from '../lib/ipcError.js'

function storage() {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

const SAVED_KEY = 'activity.needsYou.last'
const SORT_OPTIONS = [
  { value: 'unblocks', label: 'Unblocks' },
  { value: 'priority', label: 'Priority' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'project', label: 'Project' }
]

function KindPill({ priority, kind }) {
  const priorityColors = {
    p0: 'bg-red-950 text-red-300',
    p1: 'bg-orange-950 text-orange-300'
  }
  const baseColor = priority && ['p0', 'p1'].includes(priority)
    ? priorityColors[priority]
    : 'bg-neutral-800 text-neutral-300'

  const kindText = kind === 'needs-info' ? 'needs answer' : 'needs you'

  return <span className={`rounded px-2 py-1 text-xs font-medium ${baseColor}`}>{kindText}</span>
}

function NeedsYouRow({ row, boards, onOpenTicket }) {
  const boardName = boards?.find((b) => b.repo === row.projectRepo)?.name || row.projectRepo

  return (
    <button
      onClick={() => onOpenTicket(row.repo, row.number)}
      className="flex w-full flex-col gap-2 rounded border border-neutral-700 bg-neutral-800 p-3 text-left transition-colors hover:border-neutral-500 hover:bg-neutral-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 overflow-hidden">
          <div className="font-medium text-white">#{row.number} {row.title}</div>
          <div className="text-xs text-neutral-400">{boardName}</div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <KindPill priority={row.priority} kind={row.kind} />
          {row.unblocks?.count > 0 && (
            <span className="rounded bg-emerald-950 px-2 py-1 text-xs text-emerald-300">
              unblocks {row.unblocks?.count}
            </span>
          )}
        </div>
      </div>
      {row.ask && (
        <div className="text-xs text-neutral-400 line-clamp-2">{row.ask}</div>
      )}
    </button>
  )
}

export default function NeedsYou({ boards, onOpenTicket }) {
  const st = storage()
  const [sort, setSort] = useState(() => readSort(st))
  const [page, setPage] = useState(1)
  const [saved] = useState(() => readSaved(st, SAVED_KEY))
  const [rows, setRows] = useState(saved?.value || [])
  const [updatedAt, setUpdatedAt] = useState(saved?.at || null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const data = await window.api.activity.needsYou()
        if (cancelled) return

        const at = Date.now()
        writeSaved(st, SAVED_KEY, data, at)
        setRows(data)
        setUpdatedAt(at)
      } catch (e) {
        if (cancelled) return
        setError(cleanIpcError(e))
      } finally {
        if (!cancelled) {
          setLoading(false)
          setHasLoadedOnce(true)
        }
      }
    }

    load()
    const interval = setInterval(load, 5 * 60_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [st])

  const handleSort = (newSort) => {
    setSort(newSort)
    writeSort(st, newSort)
    setPage(1)
  }

  const sorted = sortRows(rows, sort)
  const { pageRows, pageCount, page: safePage } = paginate(sorted, page)

  if (rows.length === 0 && !error && !loading && hasLoadedOnce) {
    return (
      <div className="rounded border border-neutral-700 bg-neutral-800 p-6 text-center">
        <p className="text-neutral-400">Nothing needs you</p>
        {updatedAt && <p className="mt-2 text-xs text-neutral-600">{ageText(updatedAt)}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-4 rounded border border-neutral-700 bg-neutral-800 p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-white">Needs You</h3>
        <div className="flex items-center gap-2">
          {loading && <span className="text-xs text-neutral-500">updating…</span>}
          {updatedAt && !loading && <span className="text-xs text-neutral-600">{ageText(updatedAt)}</span>}
        </div>
      </div>

      {error && rows.length > 0 && (
        <div className="rounded border border-red-800 bg-red-900/30 p-3 text-xs text-red-300">
          Update failed: {error}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {SORT_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => handleSort(opt.value)}
            className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
              sort === opt.value
                ? 'bg-blue-600 text-white'
                : 'bg-neutral-700 text-neutral-300 hover:bg-neutral-600'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {rows.length > 0 ? (
        <>
          <div className="space-y-2">
            {pageRows.map((row) => (
              <NeedsYouRow key={`${row.repo}#${row.number}`} row={row} boards={boards} onOpenTicket={onOpenTicket} />
            ))}
          </div>

          {pageCount > 1 && (
            <div className="flex items-center justify-between border-t border-neutral-700 pt-3">
              <button
                onClick={() => setPage(Math.max(1, safePage - 1))}
                disabled={safePage === 1}
                className="rounded px-3 py-1 text-sm text-neutral-400 disabled:opacity-50 hover:text-neutral-200"
              >
                ‹ Previous
              </button>
              <span className="text-xs text-neutral-500">
                page {safePage} of {pageCount}
              </span>
              <button
                onClick={() => setPage(Math.min(pageCount, safePage + 1))}
                disabled={safePage === pageCount}
                className="rounded px-3 py-1 text-sm text-neutral-400 disabled:opacity-50 hover:text-neutral-200"
              >
                Next ›
              </button>
            </div>
          )}
        </>
      ) : error ? (
        <div className="rounded border border-red-800 bg-red-900 p-4 text-red-300 text-sm">
          Error loading: {error}
        </div>
      ) : null}
    </div>
  )
}
