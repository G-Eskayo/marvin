import { useEffect, useState } from 'react'
import { formatRelativeTime } from './DashboardHome.jsx'
import { projectIdOf } from '../lib/projects.js'
import { sortRows, paginate, kindLabel, priorityPill, loadSort, saveSort, loadCachedRows, saveCachedRows } from '../lib/needs_you_view.js'

const POLL_MS = 60000

export default function NeedsYouList({ onOpenTicket, boards = [] }) {
  const [rawRows, setRawRows] = useState([])
  const [sort, setSort] = useState({ field: 'unblocks', direction: 'desc' })
  const [page, setPage] = useState(0)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)

  // Initialize from cache and storage on mount
  useEffect(() => {
    try {
      const cached = typeof window !== 'undefined' ? loadCachedRows(window.localStorage) : null
      if (cached?.rows && Array.isArray(cached.rows) && cached.rows.length > 0) {
        setRawRows(cached.rows)
        if (cached.at) {
          setLastUpdated(new Date(cached.at).toISOString())
        }
      }
      const savedSort = typeof window !== 'undefined' ? loadSort(window.localStorage) : { field: 'unblocks', direction: 'desc' }
      setSort(savedSort)
    } catch {
      // Ignore cache errors, continue with empty state
    }
  }, [])

  // Refresh function that reads no component state besides the setters
  const refresh = async () => {
    try {
      setLoading(true)
      setError(null)
      const rows = await window.api.activity.needsYou()

      // Cache the fresh rows
      if (typeof window !== 'undefined') {
        saveCachedRows(rows, window.localStorage)
      }

      setRawRows(rows)
      setLastUpdated(new Date().toISOString())
    } catch (e) {
      // Keep rendering rawRows, show error as adjacent note
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }

  // Fetch on mount + set interval
  useEffect(() => {
    refresh()
    const i = setInterval(refresh, POLL_MS)
    return () => clearInterval(i)
  }, [])

  // Listen for activity triggers
  useEffect(() => {
    const handleTrigger = (t) => {
      if (t.topic === 'activity') {
        refresh()
      }
    }
    if (typeof window !== 'undefined' && window.api?.triggers?.on) {
      const unsubscribe = window.api.triggers.on(handleTrigger)
      return () => unsubscribe?.()
    }
  }, [])

  // Handle sort button click: toggle if same field, else default direction for that field
  const handleSort = (field) => {
    let newDir = 'asc'
    const defaultDir = { priority: 'asc', unblocks: 'desc', age: 'desc', project: 'asc' }[field] || 'asc'

    if (sort.field === field) {
      newDir = sort.direction === 'asc' ? 'desc' : 'asc'
    } else {
      newDir = defaultDir
    }
    const newSort = { field, direction: newDir }
    setSort(newSort)
    setPage(0)
    if (typeof window !== 'undefined') {
      saveSort(field, newDir, window.localStorage)
    }
  }

  // Derive visible page at render time
  const sorted = sortRows(rawRows, sort.field, sort.direction)
  const paged = paginate(sorted, 5, page)
  const relTime = formatRelativeTime(lastUpdated)

  return (
    <section className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900">
      <div className="flex items-center justify-between border-b border-neutral-800 p-3">
        <h2 className="text-sm font-medium text-neutral-200">
          Needs you <span className="text-neutral-500">· {paged.total} items</span>
        </h2>
        <div className="flex items-center gap-3">
          {relTime && <span className="text-xs text-neutral-600">updated {relTime}</span>}
          {loading && !relTime && <span className="text-xs text-neutral-500">updating…</span>}
        </div>
      </div>

      <div className="border-b border-neutral-800 p-3">
        {error && <p className="text-xs text-red-400 mb-2">{error}</p>}
        {!error && paged.total === 0 && (
          <p className="text-xs text-neutral-500">Nothing needs you</p>
        )}
        {!error && paged.total > 0 && (
          <>
            <div className="mb-3 flex items-center gap-2 text-xs">
              <button
                onClick={() => handleSort('priority')}
                className={`px-2 py-1 rounded ${sort.field === 'priority' ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
              >
                Priority {sort.field === 'priority' && (sort.direction === 'asc' ? '↑' : '↓')}
              </button>
              <button
                onClick={() => handleSort('unblocks')}
                className={`px-2 py-1 rounded ${sort.field === 'unblocks' ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
              >
                Unblocks {sort.field === 'unblocks' && (sort.direction === 'asc' ? '↑' : '↓')}
              </button>
              <button
                onClick={() => handleSort('age')}
                className={`px-2 py-1 rounded ${sort.field === 'age' ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
              >
                Oldest {sort.field === 'age' && (sort.direction === 'asc' ? '↑' : '↓')}
              </button>
              <button
                onClick={() => handleSort('project')}
                className={`px-2 py-1 rounded ${sort.field === 'project' ? 'bg-neutral-700 text-white' : 'bg-neutral-800 text-neutral-400 hover:text-white'}`}
              >
                Project {sort.field === 'project' && (sort.direction === 'asc' ? '↑' : '↓')}
              </button>
            </div>

            <ol className="space-y-2">
              {paged.items.map((row) => {
                const projectId = row.project || projectIdOf(row.repo)
                const board = boards.find((b) => projectIdOf(b.repo) === projectId)
                const projectName = board?.name || projectId
                const pill = priorityPill(row.priority)
                const kind = kindLabel(row.kind)

                return (
                  <li
                    key={`${row.repo}#${row.number}`}
                    className="flex flex-col gap-1 rounded border border-neutral-700 bg-neutral-800/50 p-2 hover:border-neutral-600 hover:bg-neutral-800"
                  >
                    <div className="flex items-baseline gap-2">
                      {pill && (
                        <span className={`shrink-0 rounded px-1.5 text-xs ${pill.colorClass}`}>
                          {pill.label}
                        </span>
                      )}
                      {kind && (
                        <span className="shrink-0 text-xs text-neutral-400">
                          {kind}
                        </span>
                      )}
                      <span className="shrink-0 text-xs text-neutral-500">
                        {projectName}
                      </span>
                      <button
                        onClick={() => onOpenTicket?.(row.repo, row.number)}
                        className="truncate text-left text-sm text-white hover:text-blue-300"
                      >
                        #{row.number} {row.title}
                      </button>
                      {row.unblocks?.count > 0 && (
                        <span className="ml-auto shrink-0 text-xs text-green-400">
                          +{row.unblocks.count} unblock{row.unblocks.count !== 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                    {row.ask && (
                      <div className="text-xs text-neutral-400">
                        <span className="font-medium">Ask:</span> {row.ask}
                      </div>
                    )}
                  </li>
                )
              })}
            </ol>

            {paged.total > 5 && (
              <div className="mt-3 flex items-center justify-between border-t border-neutral-700 pt-2">
                <span className="text-xs text-neutral-500">
                  Page {paged.pageNum + 1} of {Math.ceil(paged.total / paged.pageSize)}
                </span>
                <div className="flex gap-1">
                  <button
                    onClick={() => setPage(Math.max(0, page - 1))}
                    disabled={!paged.hasPrev}
                    className="rounded bg-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    ‹
                  </button>
                  <button
                    onClick={() => setPage(page + 1)}
                    disabled={!paged.hasNext}
                    className="rounded bg-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:bg-neutral-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    ›
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
