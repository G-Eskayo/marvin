import { useEffect, useState } from 'react'
import { readSaved, writeSaved, ageText } from '../lib/saved_state.js'
import { cleanIpcError } from '../lib/ipcError.js'
import {
  sortRows, paginate, priorityPill, kindLabel, getSortOptions, applyLoadResult,
  readSortPreference, writeSortPreference
} from '../lib/needs_you_view.js'

const SAVED_KEY = 'needsYou.rows'

function storage() {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

export default function NeedsYouList({ onOpenTicket }) {
  const [saved] = useState(() => readSaved(storage(), SAVED_KEY))
  const [rows, setRows] = useState(() => saved?.value ?? [])
  const [updatedAt, setUpdatedAt] = useState(saved?.at ?? null)
  const [loading, setLoading] = useState(!saved)
  const [error, setError] = useState(null)
  const [sortBy, setSortBy] = useState(() => readSortPreference(storage()))
  const [currentPage, setCurrentPage] = useState(1)
  const [, tick] = useState(0)

  const load = async () => {
    setLoading(true)
    try {
      const data = await window.api.activity.needsYou()
      const result = applyLoadResult(rows, data)
      setRows(result)
      setError(null)
      const now = Date.now()
      writeSaved(storage(), SAVED_KEY, result, now)
      setUpdatedAt(now)
    } catch (e) {
      setError(cleanIpcError(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000)
    return () => clearInterval(t)
  }, [])

  const handleSortChange = (newSort) => {
    setSortBy(newSort)
    writeSortPreference(storage(), newSort)
    setCurrentPage(1)
  }

  const sorted = sortRows(rows, sortBy)
  const paginated = paginate(sorted, currentPage, 5)

  return (
    <section className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900">
      <div className="border-b border-neutral-800 p-4">
        <h2 className="mb-3 text-sm font-medium text-neutral-200">What needs you</h2>
        <div className="flex flex-wrap items-center gap-2">
          {getSortOptions().map((opt) => (
            <button
              key={opt.id}
              onClick={() => handleSortChange(opt.id)}
              className={`rounded px-2 py-1 text-xs ${
                sortBy === opt.id
                  ? 'bg-blue-700 text-white'
                  : 'bg-neutral-800 text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {opt.label}
            </button>
          ))}
          {updatedAt != null && (
            <span className="ml-auto text-[11px] text-neutral-600">
              {loading ? 'updating…' : ageText(updatedAt)}
            </span>
          )}
        </div>
      </div>

      <div className="p-4">
        {error && (
          <p className="mb-3 text-sm text-amber-300">
            {error}
            {rows.length > 0 ? ' Showing the last good result.' : ''}
          </p>
        )}

        {rows.length === 0 && !loading ? (
          <p className="text-sm text-neutral-500">Nothing needs you</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : (
          <>
            <div className="space-y-2">
              {paginated.rows.map((row) => {
                const pill = priorityPill(row.priority)
                const repoName = row.repo?.split('/')[1] || row.repo || ''
                return (
                  <button
                    key={`${row.repo}#${row.number}`}
                    onClick={() => onOpenTicket?.(row.repo, row.number)}
                    className="w-full rounded border border-neutral-700 bg-neutral-800 p-3 text-left hover:border-neutral-600 hover:bg-neutral-700 transition-colors"
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-neutral-700 px-2 py-0.5 text-[10px] text-neutral-300 font-medium">
                        {row.project || repoName}
                      </span>
                      <span className="whitespace-nowrap rounded bg-neutral-700 px-1.5 text-[10px] text-neutral-300">
                        {kindLabel(row.kind)}
                      </span>
                      {pill && (
                        <span className={`whitespace-nowrap rounded px-1.5 text-[10px] ${pill.className}`}>
                          {pill.text}
                        </span>
                      )}
                    </div>
                    <div className="mb-2">
                      <p className="text-sm font-medium text-neutral-100">{row.title}</p>
                      <p className="mt-0.5 text-xs text-neutral-500">{repoName} #{row.number}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-neutral-500">
                      <span>{row.ask || '—'}</span>
                      {(row.unblocks?.count ?? 0) > 0 && (
                        <span className="text-blue-300">
                          ↗ unblocks {row.unblocks.count}
                        </span>
                      )}
                      {row.ageDays > 0 && <span>{row.ageDays}d old</span>}
                    </div>
                  </button>
                )
              })}
            </div>

            {paginated.totalPages > 1 && (
              <div className="mt-4 flex items-center justify-center gap-2">
                <button
                  onClick={() => setCurrentPage(Math.max(1, paginated.currentPage - 1))}
                  disabled={paginated.currentPage === 1}
                  className="rounded bg-neutral-800 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
                >
                  ← Prev
                </button>
                <span className="text-xs text-neutral-500">
                  {paginated.currentPage} of {paginated.totalPages}
                </span>
                <button
                  onClick={() => setCurrentPage(Math.min(paginated.totalPages, paginated.currentPage + 1))}
                  disabled={paginated.currentPage === paginated.totalPages}
                  className="rounded bg-neutral-800 px-2 py-1 text-xs text-neutral-400 hover:text-neutral-200 disabled:opacity-50"
                >
                  Next →
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
