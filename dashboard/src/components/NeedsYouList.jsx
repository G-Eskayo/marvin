import { useEffect, useState } from 'react'
import { sortRows, paginate, pillStyle, kindLabel, readCache, writeCache, readSortPref, writeSortPref, shouldApply, SORTS, resolveProject, initialViewState, applyFetchError, emptyStateText, freshnessText } from '../lib/needs_you_view.js'

const POLL_MS = 60000

export default function NeedsYouList({ onOpenTicket, storage = typeof window !== 'undefined' ? window.localStorage : {} }) {
  const [state, setState] = useState(() => initialViewState(storage))

  useEffect(() => {
    let cancelled = false
    let reqCounter = 0

    const refresh = async () => {
      const reqId = ++reqCounter
      try {
        const [needed, boards] = await Promise.all([
          window.api.activity.needsYou(),
          window.api.boards.list()
        ])

        if (!cancelled && shouldApply(reqId, reqCounter)) {
          const sorted = sortRows(needed, state.sortKey, boards)
          setState((prev) => ({
            ...prev,
            rows: sorted,
            boards,
            lastUpdated: Date.now(),
            status: 'ok',
            error: null
          }))
          writeCache(storage, sorted, Date.now())
        }
      } catch (e) {
        if (!cancelled) {
          setState((prev) => applyFetchError(prev, String(e.message || e)))
        }
      }
    }

    refresh()
    const i = setInterval(refresh, POLL_MS)
    const off = window.api?.triggers?.on?.((t) => {
      if ((t.topic === 'activity' || t.topic === 'mr') && !cancelled) refresh()
    })

    return () => {
      cancelled = true
      clearInterval(i)
      off?.()
    }
  }, [storage])

  const handleSortChange = (key) => {
    writeSortPref(storage, key)
    setState((prev) => {
      const sorted = sortRows(prev.rows, key, prev.boards || [])
      return { ...prev, sortKey: key, rows: sorted, page: 1 }
    })
  }

  const { rows, sortKey, lastUpdated, status, error, page } = state
  const sorted = sortRows(rows, sortKey, state.boards || [])
  const { page: currentPage, totalPages, pageRows } = paginate(sorted, page, 5)

  return (
    <section className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900">
      <div className="flex items-center justify-between border-b border-neutral-800 p-3">
        <h2 className="text-sm font-medium text-neutral-200">
          What's waiting on you {rows.length > 0 && <span className="text-neutral-500">· {rows.length} total</span>}
        </h2>
        {rows.length > 0 && (
          <select
            value={sortKey}
            onChange={(e) => handleSortChange(e.target.value)}
            className="rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-xs text-neutral-300"
          >
            {SORTS.map((key) => (
              <option key={key} value={key}>
                {key.charAt(0).toUpperCase() + key.slice(1)}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="border-t border-neutral-800 p-3">
        <p className="mb-3 text-xs text-neutral-500">{freshnessText({ status, error, lastUpdated })}</p>

        {error && <p className="mb-3 text-xs text-red-400">{error}</p>}

        {rows.length === 0 && (
          <p className="text-xs text-neutral-500">
            {emptyStateText(status)}
          </p>
        )}

        {rows.length > 0 && pageRows.length > 0 && (
          <>
            <ul className="space-y-3">
              {pageRows.map((row) => {
                const pillClasses = pillStyle(row.priority)
                const projInfo = resolveProject(row, state.boards || [])
                return (
                  <li key={`${row.repo}#${row.number}`} className="rounded border border-neutral-800 p-2 text-xs">
                    <div className="mb-1 flex items-baseline gap-2">
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${pillClasses.container} ${pillClasses.text}`}>
                        {kindLabel(row.kind)}
                      </span>
                      <button
                        onClick={() => onOpenTicket?.(row.repo, row.number)}
                        className="truncate text-left font-medium hover:text-white"
                      >
                        #{row.number} {row.title}
                      </button>
                      {row.priority && <span className="ml-auto shrink-0 text-neutral-500">{row.priority}</span>}
                    </div>

                    <div className="mb-1 text-neutral-400">{row.ask}</div>

                    {projInfo && (
                      <div className="mb-1 text-[10px] text-neutral-600">
                        Project: <span className="text-neutral-400">{projInfo.name}</span>
                      </div>
                    )}

                    {row.unblocks.count > 0 && (
                      <div className="text-[10px] text-neutral-600">
                        Unblocks {row.unblocks.count} item{row.unblocks.count !== 1 ? 's' : ''}: {' '}
                        {row.unblocks.items.map((item) => `#${item.number} ${item.title}`).join(', ')}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>

            {totalPages > 1 && (
              <div className="mt-3 flex items-center justify-between border-t border-neutral-800 pt-3 text-xs">
                <button
                  onClick={() => setState((prev) => ({ ...prev, page: Math.max(1, prev.page - 1) }))}
                  disabled={currentPage === 1}
                  className="rounded border border-neutral-700 px-2 py-1 text-neutral-400 disabled:opacity-50 hover:enabled:text-neutral-200"
                >
                  ‹
                </button>
                <span className="text-neutral-500">
                  Page {currentPage} of {totalPages}
                </span>
                <button
                  onClick={() => setState((prev) => ({ ...prev, page: Math.min(totalPages, prev.page + 1) }))}
                  disabled={currentPage === totalPages}
                  className="rounded border border-neutral-700 px-2 py-1 text-neutral-400 disabled:opacity-50 hover:enabled:text-neutral-200"
                >
                  ›
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
