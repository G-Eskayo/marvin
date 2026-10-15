import { useEffect, useState } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'
import { paginate, sortRows, readSort, writeSort, resolveProjectFor, priorityPill, kindLabel } from '../lib/needs_you_view.js'
import { readSaved, writeSaved, ageText } from '../lib/saved_state.js'

const POLL_MS = 60000
const SAVED_KEY = 'needs-you-list'

function storage() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

export default function NeedsYouList({ onOpenTicket }) {
  const [state, setState] = useState(() => ({
    rows: readSaved(storage(), SAVED_KEY)?.value || null,
    error: null
  }))
  const [boards, setBoards] = useState([])
  const [sortBy, setSortBy] = useState(readSort())
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(true)
  const [updatedAt, setUpdatedAt] = useState(readSaved(storage(), SAVED_KEY)?.at || null)

  useEffect(() => {
    let cancelled = false

    const refresh = async () => {
      try {
        const [ticketsData, boardsList] = await Promise.all([
          window.api.activity.needsYou(),
          window.api.boards.list()
        ])
        if (!cancelled) {
          const now = Date.now()
          setState({ rows: ticketsData, error: null })
          writeSaved(storage(), SAVED_KEY, ticketsData, now)
          setUpdatedAt(now)
          setBoards(boardsList)
        }
      } catch (e) {
        if (!cancelled) {
          setState((prev) => ({ ...prev, error: cleanIpcError(e) }))
        }
      }
    }

    refresh()
    const i = setInterval(refresh, POLL_MS)

    // Subscribe to refresh triggers
    const unsubscribe = window.api.triggers?.on?.(() => {
      refresh()
    })

    return () => {
      cancelled = true
      clearInterval(i)
      unsubscribe?.()
    }
  }, [])

  const handleSortChange = (newSort) => {
    setSortBy(newSort)
    writeSort(newSort)
  }

  const { rows, error } = state

  if (!rows) {
    return (
      <section className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900">
        <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between p-3 text-left">
          <span className="text-sm font-medium text-neutral-200">Needs you</span>
          <span className="text-xs text-neutral-500">{open ? 'hide' : 'show'}</span>
        </button>
        {open && (
          <div className="border-t border-neutral-800 p-3">
            {error && <p className="text-xs text-red-400">Error: {error}</p>}
            {!error && <p className="text-xs text-neutral-500">Loading…</p>}
          </div>
        )}
      </section>
    )
  }

  const sorted = sortRows(rows, sortBy)
  const paginated = paginate(sorted, { page, pageSize: 10 })

  return (
    <section className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between p-3 text-left">
        <span className="text-sm font-medium text-neutral-200">
          Needs you{rows.length > 0 && <span className="text-neutral-500"> · {rows.length} ticket{rows.length !== 1 ? 's' : ''}</span>}
          {updatedAt && <span className="text-[11px] text-neutral-600"> {ageText(updatedAt)}</span>}
        </span>
        <span className="text-xs text-neutral-500">{open ? 'hide' : 'show'}</span>
      </button>
      {open && (
        <div className="border-t border-neutral-800 p-3">
          {error && <p className="text-xs text-red-400">Error: {error}</p>}
          {rows.length === 0 && <p className="text-xs text-neutral-500">Nothing needs you</p>}
          {rows.length > 0 && (
            <>
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex gap-1">
                  {['unblocks', 'priority', 'age', 'kind'].map((opt) => (
                    <button
                      key={opt}
                      onClick={() => handleSortChange(opt)}
                      className={`rounded px-2 py-1 text-xs transition-colors ${
                        sortBy === opt
                          ? 'bg-neutral-600 text-white'
                          : 'bg-neutral-800 text-neutral-400 hover:bg-neutral-700'
                      }`}
                    >
                      {opt === 'unblocks' ? 'Unblocks' : opt === 'priority' ? 'Priority' : opt === 'age' ? 'Age' : 'Kind'}
                    </button>
                  ))}
                </div>
              </div>
              <ol className="space-y-2">
                {paginated.rows.map((r) => {
                  const project = resolveProjectFor(r.projectId, boards)
                  const priority = priorityPill(r.priority)
                  const kind = kindLabel(r.kind)
                  return (
                    <li
                      key={`${r.repo}#${r.number}`}
                      className="flex flex-col gap-1 rounded border border-neutral-700 bg-neutral-800/50 p-2 hover:bg-neutral-700/50"
                    >
                      <button
                        onClick={() => onOpenTicket?.(r.repo, r.number)}
                        className="text-left hover:text-white"
                      >
                        <div className="flex items-baseline gap-2">
                          <span className="text-xs font-medium text-neutral-300">{project.name || r.projectId}</span>
                          <span className="text-sm text-white">#{r.number} {r.title}</span>
                        </div>
                      </button>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] ${kind.class}`}>{kind.label}</span>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] ${priority.class}`}>{priority.label}</span>
                        {r.ask && <span className="text-[10px] text-neutral-400">{r.ask}</span>}
                        {r.unblocks?.count > 0 && <span className="text-[10px] text-amber-300">unblocks {r.unblocks.count}</span>}
                      </div>
                    </li>
                  )
                })}
              </ol>
              {paginated.totalPages > 1 && (
                <div className="mt-3 flex items-center justify-between border-t border-neutral-700 pt-2">
                  <button
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={paginated.currentPage === 1}
                    className="rounded px-2 py-1 text-xs text-neutral-400 disabled:opacity-50 hover:text-white"
                  >
                    ← Previous
                  </button>
                  <span className="text-xs text-neutral-500">
                    Page {paginated.currentPage} of {paginated.totalPages}
                  </span>
                  <button
                    onClick={() => setPage(Math.min(paginated.totalPages, page + 1))}
                    disabled={paginated.currentPage === paginated.totalPages}
                    className="rounded px-2 py-1 text-xs text-neutral-400 disabled:opacity-50 hover:text-white"
                  >
                    Next →
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
