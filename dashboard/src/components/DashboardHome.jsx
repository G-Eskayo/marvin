import { useEffect, useState } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'

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

export default function DashboardHome({ onOpenProject }) {
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
  const [showArchived, setShowArchived] = useState(false)

  return (
    <div className="max-w-6xl space-y-6 p-6">
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
            <div className="space-y-1">
              {archived.map((card) => (
                <button
                  key={card.repo}
                  onClick={() => onOpenProject(card.repo)}
                  className="block w-full rounded px-3 py-2 text-left text-sm text-neutral-500 transition-colors hover:bg-neutral-800/30 hover:text-neutral-300"
                >
                  {card.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
