import { useEffect, useState, useReducer } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'
import { sortRows, paginate, priorityPill, kindLabel, readCache, writeCache, readSort, writeSort, applyFetch } from '../lib/needs_you_view.js'

// Format ISO timestamp relative to now: "just now", "5m ago", "2h ago", "3d ago", "2w ago", or short date
export function formatRelativeTime(iso, now = Date.now()) {
  if (!iso) return null
  try {
    const ms = now - Date.parse(iso)
    if (ms < 60000) return 'just now'
    const mins = Math.floor(ms / 60000)
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(ms / 3600000)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(ms / 86400000)
    if (days < 7) return `${days}d ago`
    const weeks = Math.floor(days / 7)
    if (weeks < 12) return `${weeks}w ago`
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

// Combine board info, activity overview, and per-repo summaries into project cards
export function buildProjectCards(boards, overview = {}, summaries = {}) {
  return boards.map((board) => {
    const act = overview[board.repo] || {}
    const summary = summaries[board.repo] || { open: 0, running: false }
    return {
      repo: board.repo,
      name: board.name,
      status: board.status,
      isArchived: board.status === 'archived',
      open: summary.open || 0,
      running: summary.running || false,
      review: act.review || 0,
      needsYou: act.needsYou || 0,
      due: board.due || null,
      dueHard: board.dueHard || false,
      lastActivity: board.lastActivity || null
    }
  })
}

// Presentational list for needsYou rows (pure props, no storage access)
export function NeedsYouList({ rows, onOpenTicket, sortKey, currentPage, pageSize, onSort, onPageChange }) {
  const sorted = sortRows(rows, sortKey || 'default')
  const paginated = paginate(sorted, currentPage, pageSize)

  if (rows.length === 0) {
    return <p className="text-neutral-500">Nothing needs you</p>
  }

  const pill = rows.length > 0 && rows[0].priority ? priorityPill(rows[0].priority) : null
  const sortOptions = ['default', 'priority', 'unblocks', 'age', 'project']

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <label className="text-xs text-neutral-400">Sort:</label>
        <select
          value={sortKey || 'default'}
          onChange={(e) => onSort?.(e.target.value)}
          className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-xs text-white"
        >
          {sortOptions.map((opt) => (
            <option key={opt} value={opt}>
              {opt === 'default' ? 'Default' : opt.charAt(0).toUpperCase() + opt.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-2">
        {paginated.items.map((row) => {
          const pillData = priorityPill(row.priority)
          return (
            <button
              key={`${row.repo}#${row.number}`}
              onClick={() => onOpenTicket?.(row.repo, row.number)}
              className="w-full flex flex-col gap-2 rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition-colors hover:border-neutral-600"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-white">
                    #{row.number} {row.title}
                  </p>
                  <p className="text-xs text-neutral-500">{row.repo}</p>
                </div>
                {pillData && (
                  <span className={`rounded px-2 py-1 text-xs whitespace-nowrap ${pillData.className}`}>
                    {pillData.text}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="rounded bg-neutral-800 px-2 py-1 text-xs text-neutral-300">
                  {kindLabel(row.kind)}
                </span>
                {row.project && (
                  <span className="rounded bg-neutral-700 px-2 py-1 text-xs text-neutral-300">
                    {row.project}
                  </span>
                )}
                {row.unblocks.count > 0 && (
                  <span className="rounded bg-green-950 px-2 py-1 text-xs text-green-300">
                    unblocks {row.unblocks.count}
                  </span>
                )}
                <span className="text-xs text-neutral-500">{row.ageDays}d old</span>
              </div>
              <p className="text-xs text-neutral-400">{row.ask}</p>
            </button>
          )
        })}
      </div>
      {paginated.totalPages > 1 && (
        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            onClick={() => onPageChange?.(Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
            className="text-xs text-neutral-500 hover:text-neutral-300 disabled:opacity-50"
          >
            ← Prev
          </button>
          <span className="text-xs text-neutral-500">
            Page {paginated.currentPage} of {paginated.totalPages}
          </span>
          <button
            onClick={() => onPageChange?.(Math.min(paginated.totalPages, currentPage + 1))}
            disabled={currentPage === paginated.totalPages}
            className="text-xs text-neutral-500 hover:text-neutral-300 disabled:opacity-50"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}

// Stateful wrapper: reads cache, calls API, subscribes to updates
function NeedsYouSection({ onOpenTicket }) {
  const pageSize = 5
  const [state, dispatch] = useReducer(applyFetch, {
    loading: false,
    error: null,
    rows: readCache(typeof window !== 'undefined' ? window.localStorage : null) || [],
    sortKey: readSort(typeof window !== 'undefined' ? window.localStorage : null),
    page: 1,
    lastFetch: null,
    requestId: null
  })

  useEffect(() => {
    let live = true
    const requestId = `needsyou-${Date.now()}-${Math.random().toString(36).slice(2)}`

    const refresh = async () => {
      try {
        dispatch({ type: 'FETCH_START', payload: { requestId } })
        const rows = await window.api.activity.needsYou()
        if (live) {
          dispatch({ type: 'FETCH_SUCCESS', payload: { rows, at: Date.now(), requestId } })
          writeCache(typeof window !== 'undefined' ? window.localStorage : null, rows)
        }
      } catch (e) {
        if (live) {
          dispatch({ type: 'FETCH_ERROR', payload: { error: cleanIpcError(e), requestId } })
        }
      }
    }

    refresh()

    // Subscribe to background refresh
    let unsubscribe
    if (window.api?.triggers?.on) {
      unsubscribe = window.api.triggers.on('activity', async (trigger) => {
        if (live && trigger === 'activity') {
          refresh()
        }
      })
    }

    return () => {
      live = false
      if (unsubscribe) unsubscribe()
    }
  }, [])

  if (state.loading && state.rows.length === 0) {
    return <p className="text-neutral-500">Loading…</p>
  }

  if (state.error && state.rows.length === 0) {
    return <p className="text-red-400">Failed to load: {state.error}</p>
  }

  return (
    <NeedsYouList
      rows={state.rows}
      onOpenTicket={onOpenTicket}
      sortKey={state.sortKey}
      currentPage={state.page}
      pageSize={pageSize}
      onSort={(key) => {
        dispatch({ type: 'SET_SORT', payload: { key } })
        writeSort(typeof window !== 'undefined' ? window.localStorage : null, key)
      }}
      onPageChange={(page) => {
        dispatch({ type: 'SET_PAGE', payload: { page } })
      }}
    />
  )
}

function ProjectCard({ card, onOpen }) {
  const relTime = formatRelativeTime(card.lastActivity)
  return (
    <button
      onClick={() => onOpen(card.repo)}
      className="flex flex-col gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition-colors hover:border-neutral-600"
    >
      <div>
        <h3 className="text-base font-medium text-white">{card.name}</h3>
        <p className="text-xs text-neutral-500">{card.repo}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {card.open > 0 && (
          <span className="rounded bg-neutral-800 px-2 py-1 text-xs text-neutral-300">
            {card.open} open
          </span>
        )}
        {card.running && (
          <span className="rounded bg-blue-950 px-2 py-1 text-xs text-blue-300">
            ⚡ Running now
          </span>
        )}
        {card.review > 0 && (
          <span className="rounded bg-amber-950 px-2 py-1 text-xs text-amber-300">
            {card.review} in review
          </span>
        )}
        {card.needsYou > 0 && (
          <span className="rounded bg-sky-950 px-2 py-1 text-xs text-sky-300">
            {card.needsYou} needs you
          </span>
        )}
      </div>
      {(card.due || card.lastActivity) && (
        <div className="flex items-center gap-2 border-t border-neutral-800 pt-2">
          {card.due && (
            <span className={`text-xs ${card.dueHard ? 'text-red-400' : 'text-neutral-500'}`}>
              Due {new Date(card.due).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
            </span>
          )}
          {card.lastActivity && (
            <span className="text-xs text-neutral-600">
              last active {relTime}
            </span>
          )}
        </div>
      )}
    </button>
  )
}

export default function DashboardHome({ onOpenProject, onOpenTicket }) {
  // Every hook before any early return: a hook after the "no boards yet" return ran only once boards loaded, and
  // React blanked the Activity tab (error #310, 2026-10-09).
  const [showArchived, setShowArchived] = useState(false)
  const [boards, setBoards] = useState(null)
  const [overview, setOverview] = useState(null)
  const [summaries, setSummaries] = useState({})
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const [boardsList, act] = await Promise.all([
          window.api.boards.list(),
          window.api.activity.overview()
        ])
        setBoards(boardsList)
        setOverview(act)

        // Fetch summaries in parallel, swallow individual failures
        const sums = {}
        await Promise.all(
          boardsList
            .filter((b) => b.status !== 'archived')
            .map((b) =>
              window.api.boards
                .summary(b.repo)
                .then((s) => {
                  sums[b.repo] = s
                })
                .catch(() => {})
            )
        )
        setSummaries(sums)
      } catch (e) {
        setError(cleanIpcError(e))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-neutral-500">Loading projects…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <p className="text-red-400">Failed to load projects: {error}</p>
      </div>
    )
  }

  if (!boards || boards.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-neutral-500">No project boards yet</p>
      </div>
    )
  }

  const cards = buildProjectCards(boards, overview, summaries)
  const active = cards.filter((c) => !c.isArchived)
  const archived = cards.filter((c) => c.isArchived)

  return (
    <div className="max-w-6xl space-y-6 p-6">
      <div>
        <h2 className="mb-4 text-xl font-semibold text-white">What needs you</h2>
        <NeedsYouSection onOpenTicket={onOpenTicket} />
      </div>

      <div>
        <h1 className="mb-4 text-2xl font-semibold text-white">Project Boards</h1>
        <div className="grid auto-fit gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
          {active.map((card) => (
            <ProjectCard key={card.repo} card={card} onOpen={onOpenProject} />
          ))}
        </div>
      </div>

      {archived.length > 0 && (
        <div>
          <button
            onClick={() => setShowArchived(!showArchived)}
            className="mb-3 flex items-center gap-2 text-sm text-neutral-500 hover:text-neutral-300"
          >
            <span>{showArchived ? '▾' : '▸'}</span>
            <span>Archived ({archived.length})</span>
          </button>
          {showArchived && (
            // The same card as an active project, dimmed: one look for every board (Gil, 2026-10-09).
            <div className="grid auto-fit gap-4 opacity-60" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
              {archived.map((card) => (
                <ProjectCard key={card.repo} card={card} onOpen={onOpenProject} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
