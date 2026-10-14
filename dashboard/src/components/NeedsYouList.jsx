import { useEffect, useState, useRef } from 'react'
import { paginate, sortRows, describeNeedsYouRow, shouldApplyCachedRows } from '../lib/needs_you_view.js'

const REFRESH_MS = 60_000 // 1 minute fallback poll

function formatRelativeTime(timestamp) {
  if (typeof timestamp !== 'number') return 'unknown time'
  const ageMs = Date.now() - timestamp
  const ageSecs = Math.floor(ageMs / 1000)
  const ageMins = Math.floor(ageMs / 60_000)
  const ageHours = Math.floor(ageMs / 3600_000)

  if (ageSecs < 60) return `${ageSecs}s ago`
  if (ageMins < 60) return `${ageMins}m ago`
  if (ageHours < 24) return `${ageHours}h ago`
  return `${Math.floor(ageMs / 86400_000)}d ago`
}

export default function NeedsYouList({ onOpenTicket }) {
  const [rows, setRows] = useState(null) // null until first load
  const [sort, setSort] = useState(null) // null = default
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [at, setAt] = useState(null) // timestamp of last success
  const refreshRef = useRef(null)
  const pollTimerRef = useRef(null)

  // Load cached state once on mount for instant paint
  useEffect(() => {
    const loadCached = async () => {
      const cached = await window.api.activity.needsYouState()
      if (shouldApplyCachedRows(cached)) {
        setRows(cached.rows)
        setSort(cached.sort || null)
        setAt(cached.at)
      }
    }
    loadCached()
  }, [])

  // Fetch fresh data in the background; set refreshRef before setRows
  const refresh = async () => {
    setLoading(true)
    try {
      const fresh = await window.api.activity.needsYou()
      refreshRef.current = fresh // Store before state change
      setRows(fresh)
      setError(null)
      setAt(Date.now())
    } catch (e) {
      // On error, keep the old rows and mark them stale
      setError(e.message || 'Failed to fetch')
    } finally {
      setLoading(false)
    }
  }

  // Subscribe to activity triggers and set up fallback poll
  useEffect(() => {
    refresh() // Initial fetch

    const unsubTrigger = window.api.triggers.on((trigger) => {
      if (trigger.topic === 'activity') {
        refresh()
      }
    })

    pollTimerRef.current = setInterval(refresh, REFRESH_MS)

    return () => {
      unsubTrigger()
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [])

  // Handle sort change: call IPC and don't reset page on background refresh
  const handleSort = (newSort) => {
    setSort(newSort)
    window.api.activity.setNeedsYouSort(newSort)
  }

  // Apply sorting and pagination
  const sorted = rows ? sortRows(rows, sort) : []
  const { items, total } = paginate(sorted, page, 5)

  if (rows === null) {
    // Not loaded yet
    return (
      <div className="mx-6 my-8 p-6 bg-neutral-900 border border-neutral-700 rounded">
        <p className="text-neutral-400">Loading…</p>
      </div>
    )
  }

  if (total === 0) {
    return (
      <div className="mx-6 my-8 p-6 bg-neutral-900 border border-neutral-700 rounded">
        <p className="text-neutral-400">Nothing needs you</p>
      </div>
    )
  }

  // Status note: "updating…" / "updated Xs ago" / "updating failed, showing data from Xs ago"
  let statusNote = ''
  if (loading) {
    statusNote = 'updating…'
  } else if (error && at) {
    statusNote = `updating failed, showing data from ${formatRelativeTime(at)}`
  } else if (at) {
    statusNote = `updated ${formatRelativeTime(at)}`
  }

  return (
    <div className="mx-6 my-8">
      {/* Header with sort control */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Needs you ({total})</h2>
        <div className="flex gap-2">
          <button
            onClick={() => handleSort(null)}
            className={`px-3 py-1 text-sm rounded ${sort === null ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
          >
            Default
          </button>
          <button
            onClick={() => handleSort('priority')}
            className={`px-3 py-1 text-sm rounded ${sort === 'priority' ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
          >
            Priority
          </button>
          <button
            onClick={() => handleSort('age')}
            className={`px-3 py-1 text-sm rounded ${sort === 'age' ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
          >
            Age
          </button>
          <button
            onClick={() => handleSort('unblocks')}
            className={`px-3 py-1 text-sm rounded ${sort === 'unblocks' ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
          >
            Unblocks
          </button>
        </div>
      </div>

      {/* Status note */}
      {statusNote && (
        <div className="mb-4 text-xs text-neutral-500">
          {statusNote}
        </div>
      )}

      {/* Rows */}
      <div className="space-y-2">
        {items.map((row) => {
          const desc = describeNeedsYouRow(row)
          return (
            <button
              key={`${row.repo}#${row.number}`}
              onClick={() => onOpenTicket(row.repo, row.number)}
              className="w-full text-left p-3 bg-neutral-900 border border-neutral-700 hover:border-neutral-500 rounded transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  {/* Title and project */}
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-white font-medium truncate">{desc.title}</span>
                    <span className="text-xs text-neutral-400 shrink-0">#{desc.number}</span>
                    {desc.pill.className && (
                      <span className={`px-2 py-0.5 text-xs rounded font-semibold ${desc.pill.className} shrink-0`}>
                        {desc.pill.label}
                      </span>
                    )}
                  </div>
                  {/* Ask and project */}
                  <div className="text-sm text-neutral-400">
                    {desc.ask && <span>{desc.ask}</span>}
                    {desc.ask && <span className="mx-1">·</span>}
                    <span>{desc.repoShort}</span>
                  </div>
                  {/* Unblocks */}
                  {desc.unblocks.count > 0 && (
                    <div className="mt-1 text-xs text-green-400">
                      Unblocks {desc.unblocks.count} item{desc.unblocks.count !== 1 ? 's' : ''}
                      {desc.unblocks.items.length > 0 && (
                        <>
                          : {desc.unblocks.items.map((u) => `#${u.number}`).join(', ')}
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {/* Pagination */}
      {total > 5 && (
        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="px-3 py-1 text-sm bg-neutral-800 text-neutral-400 rounded disabled:opacity-50 hover:text-white"
          >
            ← Prev
          </button>
          <span className="text-sm text-neutral-400">
            Page {page + 1} of {Math.ceil(total / 5)}
          </span>
          <button
            onClick={() => setPage(Math.min(Math.ceil(total / 5) - 1, page + 1))}
            disabled={page >= Math.ceil(total / 5) - 1}
            className="px-3 py-1 text-sm bg-neutral-800 text-neutral-400 rounded disabled:opacity-50 hover:text-white"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}
