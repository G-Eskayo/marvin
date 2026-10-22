import { useEffect, useState } from 'react'
import { readSaved, writeSaved, ageText } from '../lib/saved_state.js'
import { paginate, sortRows, priorityStyle, readSortPreference, writeSortPreference, bodyState, sanitizeRows } from '../lib/needs_you_view.js'

const SAVED_KEY = 'needs_you.list'

function storage() {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

export function NeedsYouRow({ row, boards, onOpenTicket }) {
  const style = priorityStyle(row.priority, row.kind)
  const projectName = boards.find((b) => b.repo === row.repo)?.name || row.repo.split('/')[1]

  return (
    <button
      onClick={() => onOpenTicket?.(row.repo, row.number)}
      className="flex flex-col gap-2 border-b border-neutral-800 px-4 py-3 text-left hover:bg-neutral-800/50 transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <span className={`rounded px-2 py-1 text-xs font-medium ${style.bg} ${style.text}`}>
          {style.label}
        </span>
        <span className="text-xs text-neutral-500">#{row.number}</span>
      </div>

      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium text-white line-clamp-2">{row.title}</p>
        <p className="text-xs text-neutral-500">{projectName}</p>
      </div>

      {row.unblocks.count > 0 && (
        <div className="text-xs text-neutral-400">
          <p className="font-medium">Unblocks {row.unblocks.count} ticket{row.unblocks.count === 1 ? '' : 's'}:</p>
          <ul className="ml-2 space-y-0.5">
            {row.unblocks.items.map((item) => (
              <li key={item.number} className="truncate">• {item.title}</li>
            ))}
          </ul>
        </div>
      )}

      {row.ask && (
        <p className="text-xs text-neutral-400 italic">{row.ask}</p>
      )}
    </button>
  )
}

export default function NeedsYouList({ boards = [], onOpenTicket }) {
  const [saved] = useState(() => readSaved(storage(), SAVED_KEY))
  const [rows, setRows] = useState(() => sanitizeRows(saved ? saved.value : []))
  const [page, setPage] = useState(0)
  const [sortId, setSortId] = useState(() => readSortPreference(storage()))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showNeedsYou, setShowNeedsYou] = useState(true)
  const [, tick] = useState(0)

  const load = async () => {
    setLoading(true)
    try {
      const data = await window.api.activity.needsYou()
      const clean = sanitizeRows(data || [])
      setRows(clean)
      writeSaved(storage(), SAVED_KEY, clean)
      setError(null)
    } catch (e) {
      console.error('Failed to load needs you list:', e)
      setError(true)
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

  const handleSortChange = (newSortId) => {
    setSortId(newSortId)
    writeSortPreference(storage(), newSortId)
    setPage(0)
  }

  const sorted = sortRows(rows, sortId, { boards })
  const paginated = paginate(sorted, page, 5)

  // Clamp page when paginated count changes (e.g., after filtering/sorting)
  useEffect(() => {
    if (page >= paginated.pages && paginated.pages > 0) {
      setPage(Math.max(0, paginated.pages - 1))
    }
  }, [paginated.pages, page])

  const staleNote = saved ? ` • updated ${ageText(saved.at, Date.now())} ago` : ''
  const state = bodyState(rows, error)

  return (
    <div className="max-w-6xl space-y-3 p-6">
      <section data-testid="needs-you">
        <button
          onClick={() => setShowNeedsYou(!showNeedsYou)}
          className="mb-3 flex items-center gap-2 text-lg font-semibold text-white hover:text-neutral-300"
        >
          <span>{showNeedsYou ? '▾' : '▸'}</span>
          <span>Needs you{error && ' (error loading)'}</span>
          {error && <span className="text-xs text-neutral-500">{staleNote}</span>}
        </button>

        {showNeedsYou && (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={sortId}
                  onChange={(e) => handleSortChange(e.target.value)}
                  className="rounded bg-neutral-900 px-2 py-1 text-sm text-neutral-300 border border-neutral-700 hover:border-neutral-600"
                >
                  <option value="unblocks">Most unblocks</option>
                  <option value="priority">Highest priority</option>
                  <option value="oldest">Oldest first</option>
                  <option value="project">By project</option>
                </select>
                {loading && <span className="text-xs text-neutral-500">updating…</span>}
              </div>
            </div>

            {state === 'empty' && (
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
                <p className="text-center text-neutral-400">Nothing needs you</p>
              </div>
            )}

            {state === 'error' && (
              <>
                <p className="mb-2 text-xs text-amber-300">Couldn't load — showing saved list{staleNote}.</p>
                {rows.length === 0 ? (
                  <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
                    <p className="text-center text-neutral-400">Nothing needs you</p>
                  </div>
                ) : (
                  <>
                    <div className="rounded-lg border border-neutral-800 bg-neutral-900 overflow-hidden">
                      {paginated.items.map((row) => (
                        <NeedsYouRow
                          key={`${row.repo}#${row.number}`}
                          row={row}
                          boards={boards}
                          onOpenTicket={onOpenTicket}
                        />
                      ))}
                    </div>

                    {paginated.pages > 1 && (
                      <div className="mt-3 flex items-center justify-center gap-2">
                        <button
                          onClick={() => setPage(Math.max(0, page - 1))}
                          disabled={page === 0}
                          className="text-xs text-neutral-500 hover:text-neutral-300 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          ← Newer
                        </button>
                        <span className="text-xs text-neutral-500">
                          Page {page + 1} of {paginated.pages}
                        </span>
                        <button
                          onClick={() => setPage(Math.min(paginated.pages - 1, page + 1))}
                          disabled={page >= paginated.pages - 1}
                          className="text-xs text-neutral-500 hover:text-neutral-300 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Older →
                        </button>
                      </div>
                    )}
                  </>
                )}
              </>
            )}

            {state === 'loaded' && (
              <>
                <div className="rounded-lg border border-neutral-800 bg-neutral-900 overflow-hidden">
                  {paginated.items.map((row) => (
                    <NeedsYouRow
                      key={`${row.repo}#${row.number}`}
                      row={row}
                      boards={boards}
                      onOpenTicket={onOpenTicket}
                    />
                  ))}
                </div>

                {paginated.pages > 1 && (
                  <div className="mt-3 flex items-center justify-center gap-2">
                    <button
                      onClick={() => setPage(Math.max(0, page - 1))}
                      disabled={page === 0}
                      className="text-xs text-neutral-500 hover:text-neutral-300 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      ← Newer
                    </button>
                    <span className="text-xs text-neutral-500">
                      Page {page + 1} of {paginated.pages}
                    </span>
                    <button
                      onClick={() => setPage(Math.min(paginated.pages - 1, page + 1))}
                      disabled={page >= paginated.pages - 1}
                      className="text-xs text-neutral-500 hover:text-neutral-300 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Older →
                    </button>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </section>
    </div>
  )
}
