import { useEffect, useState } from 'react'
import { readSaved, writeSaved, ageText } from '../lib/saved_state.js'
import { paginate, sortRows, priorityPill, resolveProjectName, readSortPref, writeSortPref, SORT_ORDERS, PAGE_SIZE } from '../lib/needs_you_view.js'

const SAVED_KEY = 'needsyou.list.last'

function storage() {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

const SORT_DISPLAY_LABELS = {
  unblocks: 'Unblocks most',
  priority: 'Priority',
  oldest: 'Oldest',
  project: 'Project'
}

// Export the row-click handler logic for testing
export function makeRowClickHandler(row, onOpenTicket) {
  return () => onOpenTicket(row.repo, row.number)
}

export default function NeedsYouList({ boards, onOpenTicket }) {
  const [saved] = useState(() => readSaved(storage(), SAVED_KEY))
  const [rows, setRows] = useState(saved ? saved.value : null)
  const [updatedAt, setUpdatedAt] = useState(saved?.at ?? null)
  const [loading, setLoading] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [sortOrder, setSortOrder] = useState(() => readSortPref(storage()))

  const load = () => {
    setLoading(true)
    window.api.activity.needsYou()
      .then((newRows) => {
        setRows(newRows)
        const at = Date.now()
        writeSaved(storage(), SAVED_KEY, newRows, at)
        setUpdatedAt(at)
        setCurrentPage(1)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  useEffect(() => {
    const unsubscribe = window.api.triggers?.on?.((t) => {
      if (t.topic === 'activity') load()
    })
    return () => unsubscribe?.()
  }, [])

  const handleSortChange = (order) => {
    setSortOrder(order)
    writeSortPref(storage(), order)
    setCurrentPage(1)
  }

  if (!rows || rows.length === 0) {
    return (
      <div className="max-w-6xl space-y-6 p-6">
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-6">
          <p className="text-neutral-500">Nothing needs you</p>
        </div>
      </div>
    )
  }

  const sorted = sortRows(rows, sortOrder, boards || [])
  const paged = paginate(sorted, currentPage, PAGE_SIZE)

  return (
    <div className="max-w-6xl space-y-4 p-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-white">What needs you</h2>
          <div className="flex flex-wrap items-center gap-2">
            <nav className="flex gap-1">
              {SORT_ORDERS.map((order) => (
                <button
                  key={order}
                  onClick={() => handleSortChange(order)}
                  className={`rounded-md px-3 py-1.5 text-sm ${
                    sortOrder === order
                      ? 'bg-neutral-800 text-white'
                      : 'text-neutral-400 hover:text-neutral-200'
                  }`}
                >
                  {SORT_DISPLAY_LABELS[order]}
                </button>
              ))}
            </nav>
            {updatedAt != null && (
              <span className="text-[11px] text-neutral-600">
                {loading ? 'updating…' : ageText(updatedAt)}
              </span>
            )}
          </div>
        </div>

        <div className="space-y-2">
          {paged.items.map((row) => {
            const pill = priorityPill(row.priority, row.kind)
            const projName = resolveProjectName(row, boards || [])
            return (
              <button
                key={`${row.repo}#${row.number}`}
                onClick={makeRowClickHandler(row, onOpenTicket)}
                className="w-full rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-left transition-colors hover:border-neutral-600"
              >
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-white">#{row.number}</span>
                    <span className="text-sm text-neutral-400">{row.title}</span>
                    {pill && (
                      <span className={`rounded px-2 py-1 text-xs font-medium ${pill.className}`}>
                        {pill.label}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
                    {projName && <span>{projName}</span>}
                    {row.unblocks.count > 0 && (
                      <span className="text-blue-400">unblocks {row.unblocks.count}</span>
                    )}
                    {row.ask && <span>{row.ask}</span>}
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        {paged.totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 pt-2">
            <button
              onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
              disabled={currentPage === 1}
              className="rounded px-2 py-1 text-sm text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
            >
              Prev
            </button>
            <span className="text-xs text-neutral-600">
              {currentPage} / {paged.totalPages}
            </span>
            <button
              onClick={() => setCurrentPage(Math.min(paged.totalPages, currentPage + 1))}
              disabled={currentPage === paged.totalPages}
              className="rounded px-2 py-1 text-sm text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
