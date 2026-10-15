import { useEffect, useState } from 'react'
import { readSaved, writeSaved, ageText } from '../lib/saved_state.js'
import { pageOf, sortRows, readSort, writeSort, pillFor, kindLabel, projectNameFor } from '../lib/needs_you_view.js'

export function NeedsYouList({ rows = [], boards = [], page = 0, sort = 'unblocks', onSort, onPageChange, onOpenTicket, lastUpdate = null }) {
  const sorted = sortRows(rows, sort, boards)
  const paged = pageOf(sorted, page)

  const handleRowClick = (r) => {
    onOpenTicket?.(r.repo, r.number)
  }

  const unblocksSummary = (r) => {
    if (r.unblocks?.count === 0) return ''
    const items = r.unblocks?.items || []
    const labels = items.map((i) => `#${i.number}`).join(', ')
    return items.length > 3 ? `${labels.slice(0, 20)}…` : labels
  }

  return (
    <section className="mb-6 rounded-lg border border-neutral-800 bg-neutral-900">
      <div className="p-4">
        <h2 className="mb-3 text-base font-semibold text-white">What needs you</h2>

        {rows.length === 0 && (
          <p className="text-sm text-neutral-400">Nothing needs you</p>
        )}

        {rows.length > 0 && (
          <>
            <div className="mb-3 flex items-center justify-between gap-2 text-xs text-neutral-500">
              <div className="flex gap-2">
                <button
                  onClick={() => onSort?.('unblocks')}
                  className={`rounded px-2 py-1 transition-colors ${sort === 'unblocks' ? 'bg-neutral-700 text-neutral-100' : 'hover:bg-neutral-800'}`}
                >
                  Impact
                </button>
                <button
                  onClick={() => onSort?.('priority')}
                  className={`rounded px-2 py-1 transition-colors ${sort === 'priority' ? 'bg-neutral-700 text-neutral-100' : 'hover:bg-neutral-800'}`}
                >
                  Priority
                </button>
                <button
                  onClick={() => onSort?.('oldest')}
                  className={`rounded px-2 py-1 transition-colors ${sort === 'oldest' ? 'bg-neutral-700 text-neutral-100' : 'hover:bg-neutral-800'}`}
                >
                  Oldest
                </button>
                <button
                  onClick={() => onSort?.('project')}
                  className={`rounded px-2 py-1 transition-colors ${sort === 'project' ? 'bg-neutral-700 text-neutral-100' : 'hover:bg-neutral-800'}`}
                >
                  Project
                </button>
              </div>
              {lastUpdate && (
                <span className="text-neutral-600">{ageText(lastUpdate)}</span>
              )}
            </div>

            <div className="space-y-2">
              {paged.rows.map((r) => (
                <button
                  key={`${r.repo}#${r.number}`}
                  onClick={() => handleRowClick(r)}
                  className="w-full rounded-lg border border-neutral-700 bg-neutral-800/50 p-3 text-left transition-colors hover:border-neutral-600 hover:bg-neutral-700/50"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="shrink-0 font-mono text-sm text-neutral-400">#{r.number}</span>
                        <span className="truncate text-sm text-white">{r.title}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <span className="text-xs text-neutral-500">{projectNameFor(r, boards)}</span>
                        {pillFor(r.priority) && (
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${pillFor(r.priority)}`}>
                            {r.priority}
                          </span>
                        )}
                        <span className="text-xs text-neutral-400">{kindLabel(r.kind)}</span>
                      </div>
                      <p className="mt-1 text-xs text-neutral-500">{r.ask}</p>
                      {r.unblocks?.count > 0 && (
                        <p className="mt-1 text-xs text-blue-400">
                          Unblocks: {unblocksSummary(r)}
                        </p>
                      )}
                    </div>
                    <span className="shrink-0 text-xs text-neutral-600">{r.ageDays}d</span>
                  </div>
                </button>
              ))}
            </div>

            {paged.pages > 1 && (
              <div className="mt-3 flex items-center justify-center gap-2 text-xs text-neutral-500">
                <button
                  onClick={() => onPageChange?.(page - 1)}
                  disabled={page === 0}
                  className="rounded px-2 py-1 hover:bg-neutral-800 disabled:text-neutral-700"
                >
                  ← Previous
                </button>
                <span>
                  Page {paged.page + 1} of {paged.pages}
                </span>
                <button
                  onClick={() => onPageChange?.(page + 1)}
                  disabled={page >= paged.pages - 1}
                  className="rounded px-2 py-1 hover:bg-neutral-800 disabled:text-neutral-700"
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

export default function NeedsYouSection({ onOpenTicket }) {
  const [state, setState] = useState({ rows: [], error: null })
  const [boards, setBoards] = useState([])
  const [page, setPage] = useState(0)
  const [sort, setSort] = useState(() => readSort(typeof window !== 'undefined' ? window.localStorage : null))

  useEffect(() => {
    const loadInitial = async () => {
      try {
        const [needsYou, boardsList] = await Promise.all([
          window.api?.activity?.needsYou?.() || Promise.resolve([]),
          window.api?.boards?.list?.() || Promise.resolve([])
        ])
        setState({ rows: needsYou || [], error: null, at: Date.now() })
        setBoards(boardsList || [])
        if (typeof window !== 'undefined' && window.localStorage) {
          writeSaved(window.localStorage, 'needsYou.rows', needsYou || [])
        }
      } catch (e) {
        setState((prev) => ({
          ...prev,
          error: String(e.message || e),
          rows: prev.rows || []
        }))
      }
    }

    const saved = typeof window !== 'undefined' ? readSaved(window.localStorage, 'needsYou.rows') : null
    if (saved?.value) {
      setState({ rows: saved.value, error: null, at: saved.at })
    }

    loadInitial()

    const unsubscribe = window.api?.triggers?.on?.((trigger) => {
      if (trigger?.topic === 'activity') {
        loadInitial()
      }
    })

    return () => unsubscribe?.()
  }, [])

  const handleSort = (newSort) => {
    setSort(newSort)
    if (typeof window !== 'undefined' && window.localStorage) {
      writeSort(window.localStorage, newSort)
    }
  }

  return (
    <NeedsYouList
      rows={state.rows}
      boards={boards}
      page={page}
      sort={sort}
      lastUpdate={state.at}
      onSort={handleSort}
      onPageChange={setPage}
      onOpenTicket={onOpenTicket}
    />
  )
}
