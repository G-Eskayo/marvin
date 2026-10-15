import { useEffect, useRef, useState } from 'react'
import { readSaved, writeSaved, ageText } from '../lib/saved_state.js'
import { paginate, sortRows, pillFor, projectName, mergeNeedsYouResult, readSortChoice, writeSortChoice } from '../lib/needs_you_view.js'
import { cleanIpcError } from '../lib/ipcError.js'

const SAVED_KEY = 'needs-you.list'
const SORT_CHOICES = ['unblocks', 'priority', 'oldest', 'project']
const SORT_LABELS = {
  unblocks: 'Most Unblocks',
  priority: 'Highest Priority',
  oldest: 'Oldest First',
  project: 'By Project'
}

function storage() {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

function toneClass(tone) {
  switch (tone) {
    case 'red':
      return 'bg-red-950 text-red-300'
    case 'orange':
      return 'bg-amber-950 text-amber-300'
    case 'grey':
    default:
      return 'bg-neutral-800 text-neutral-400'
  }
}

function NeedsYouRow({ row, boardsByRepo = {}, onOpenTicket }) {
  const pill = pillFor(row)
  const pname = projectName(row, boardsByRepo)
  const handleClick = () => {
    onOpenTicket(row.repo, row.number)
  }

  return (
    <button
      onClick={handleClick}
      className="w-full border-b border-neutral-800 px-4 py-3 text-left transition-colors hover:bg-neutral-900 active:bg-neutral-800"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${toneClass(pill.tone)}`}>
              {pill.text}
            </span>
            <span className="text-xs text-neutral-600">#{row.number}</span>
          </div>
          <h3 className="mt-1 text-sm text-white">{row.title}</h3>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-400">
            {row.ask && <span>{row.ask}</span>}
            {row.unblocks?.count > 0 && (
              <span className="text-sky-400">
                unblocks {row.unblocks.count}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 text-right text-xs text-neutral-500">
          <span>{pname}</span>
          <span>{row.ageDays}d ago</span>
        </div>
      </div>
    </button>
  )
}

export default function NeedsYouList({ boards = [], onOpenTicket }) {
  const [saved] = useState(() => readSaved(storage(), SAVED_KEY))
  const [data, setData] = useState(() => (saved ? { rows: saved.value?.rows ?? [], error: null } : { rows: [], error: null }))
  const [updatedAt, setUpdatedAt] = useState(saved?.at ?? null)
  const [loading, setLoading] = useState(!saved)
  const [sort, setSort] = useState(() => readSortChoice(storage()))
  const [page, setPage] = useState(0)
  const [, tick] = useState(0)
  const reqSeq = useRef(0)

  const load = () => {
    const seq = ++reqSeq.current
    setLoading(true)
    window.api.activity
      .needsYou()
      .then((rows) => {
        const merged = mergeNeedsYouResult({ rows: data.rows, timestamp: updatedAt }, { rows, error: null }, { seq, latestSeq: reqSeq.current })
        setData({ rows: merged.rows, error: merged.error })
        if (merged.rows.length > 0) {
          writeSaved(storage(), SAVED_KEY, { rows: merged.rows }, merged.timestamp)
          setUpdatedAt(merged.timestamp)
        }
      })
      .catch((e) => {
        setData((prev) => ({ rows: prev.rows, error: cleanIpcError(e) }))
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  useEffect(() => {
    const unsubscribe = window.api.triggers.on((t) => (t.topic === 'activity' || t.topic === 'mr') && load())
    return () => unsubscribe?.()
  }, [])

  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000)
    return () => clearInterval(t)
  }, [])

  const boardsByRepo = Object.fromEntries(boards.map((b) => [b.repo, b]))
  const sorted = sortRows(data.rows, sort, boardsByRepo)
  const paginated = paginate(sorted, page, 5)

  const handleSortChange = (newSort) => {
    setSort(newSort)
    writeSortChoice(storage(), newSort)
    setPage(0)
  }

  if (loading && data.rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-neutral-500">Reading what needs you…</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Waiting on You</h2>
          {updatedAt != null && (
            <span className="text-xs text-neutral-600">
              {loading ? 'updating…' : ageText(updatedAt)}
            </span>
          )}
        </div>

        {data.error && (
          <p className="mb-3 text-sm text-amber-300">
            {data.error}
            {data.rows.length > 0 ? ' Showing the last good result.' : ''}
          </p>
        )}

        <div className="mb-4 flex flex-wrap gap-2">
          {SORT_CHOICES.map((sc) => (
            <button
              key={sc}
              onClick={() => handleSortChange(sc)}
              className={`rounded px-3 py-1.5 text-sm transition-colors ${
                sort === sc
                  ? 'bg-neutral-700 text-white'
                  : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {SORT_LABELS[sc]}
            </button>
          ))}
        </div>
      </div>

      {data.rows.length === 0 ? (
        <div className="flex h-32 items-center justify-center">
          <p className="text-neutral-500">Nothing needs you</p>
        </div>
      ) : (
        <>
          <div className="rounded border border-neutral-800 bg-neutral-950">
            {paginated.rows.map((row) => (
              <NeedsYouRow
                key={`${row.repo}#${row.number}`}
                row={row}
                boardsByRepo={boardsByRepo}
                onOpenTicket={onOpenTicket}
              />
            ))}
          </div>

          {paginated.totalPages > 1 && (
            <div className="flex items-center justify-between text-xs text-neutral-600">
              <span>
                Page {paginated.page + 1} of {paginated.totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(Math.max(0, page - 1))}
                  disabled={page === 0}
                  className="rounded px-2 py-1 disabled:opacity-50"
                >
                  ← Previous
                </button>
                <button
                  onClick={() => setPage(Math.min(paginated.totalPages - 1, page + 1))}
                  disabled={page === paginated.totalPages - 1}
                  className="rounded px-2 py-1 disabled:opacity-50"
                >
                  Next →
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
