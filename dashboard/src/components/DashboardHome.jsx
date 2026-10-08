import { useEffect, useState } from 'react'

export function formatRelativeTime(isoString, now = Date.now()) {
  if (!isoString) return null
  try {
    const time = new Date(isoString).getTime()
    const diff = now - time
    const minutes = Math.floor(diff / 60_000)
    const hours = Math.floor(diff / 3600_000)
    const days = Math.floor(diff / 86400_000)
    const weeks = Math.floor(diff / 604800_000)

    if (minutes < 1) return 'just now'
    if (minutes < 60) return `${minutes}m ago`
    if (hours < 24) return `${hours}h ago`
    if (days < 7) return `${days}d ago`
    if (weeks < 4) return `${weeks}w ago`
    return new Date(isoString).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return null
  }
}

export function buildProjectCards(boards, overview = {}, summaries = {}) {
  return (boards || []).map((board) => {
    const summary = summaries[board.repo]
    const activityData = overview[board.repo] || { review: 0, needsYou: 0, blocked: 0 }
    return {
      repo: board.repo,
      name: board.name,
      status: board.status,
      isArchived: board.status === 'archived',
      open: summary?.open || 0,
      running: summary?.running || false,
      review: activityData.review,
      needsYou: activityData.needsYou,
      due: board.due,
      dueHard: board.dueHard,
      lastActivity: formatRelativeTime(board.lastActivity)
    }
  })
}

function ProjectCard({ card, onOpenProject }) {
  return (
    <button
      onClick={() => onOpenProject(card.repo)}
      className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-left hover:border-neutral-600 transition-colors"
    >
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-medium text-white">{card.name}</h3>
        {card.open > 0 && <span className="text-xs text-neutral-400">{card.open} open</span>}
      </div>
      {card.running && <p className="mb-2 text-xs font-medium text-blue-400">⚡ Running now</p>}
      <div className="flex flex-wrap gap-2">
        {card.review > 0 && <span className="text-xs bg-amber-950 text-amber-300 rounded px-2 py-1">{card.review} in review</span>}
        {card.needsYou > 0 && <span className="text-xs bg-sky-950 text-sky-300 rounded px-2 py-1">{card.needsYou} need you</span>}
        {card.due && <span className={`text-xs rounded px-2 py-1 ${card.dueHard ? 'bg-amber-950 text-amber-300' : 'bg-neutral-800 text-neutral-400'}`}>{card.dueHard ? 'Hard' : 'Soft'} due {card.due}</span>}
        {card.lastActivity && <span className="text-xs text-neutral-500 ml-auto">{card.lastActivity}</span>}
      </div>
    </button>
  )
}

export default function DashboardHome({ onOpenProject }) {
  const [boards, setBoards] = useState(null)
  const [overview, setOverview] = useState(null)
  const [summaries, setSummaries] = useState({})
  const [error, setError] = useState(null)
  const [showArchived, setShowArchived] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const [boardsList, activityOverview] = await Promise.all([
          window.api.boards.list(),
          window.api.activity.overview()
        ])
        setBoards(boardsList)
        setOverview(activityOverview)

        const nonArchived = boardsList.filter((b) => b.status !== 'archived')
        const summaryMap = {}
        await Promise.all(
          nonArchived.map((board) =>
            window.api.boards
              .summary(board.repo)
              .then((s) => {
                summaryMap[board.repo] = s
              })
              .catch(() => {})
          )
        )
        setSummaries(summaryMap)
      } catch (e) {
        setError(String(e))
      }
    }

    load()
  }, [])

  if (!boards) return <div className="p-6 text-neutral-500">Loading…</div>
  if (boards.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-center text-neutral-500">
        <p className="text-lg font-medium text-neutral-300">No project boards yet</p>
        <p className="max-w-md text-sm">A board appears when MARVIN starts working on a project.</p>
      </div>
    )
  }

  const cards = buildProjectCards(boards, overview, summaries)
  const active = cards.filter((c) => !c.isArchived)
  const archived = cards.filter((c) => c.isArchived)

  return (
    <div className="p-6 space-y-6">
      {error && <p className="text-red-400">{error}</p>}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {active.map((card) => (
          <ProjectCard key={card.repo} card={card} onOpenProject={onOpenProject} />
        ))}
      </div>

      {archived.length > 0 && (
        <div className="pt-4 border-t border-neutral-800">
          <button
            onClick={() => setShowArchived(!showArchived)}
            className="text-xs text-neutral-500 hover:text-neutral-300 flex items-center gap-1"
          >
            {showArchived ? '▾' : '▸'} Archived ({archived.length})
          </button>
          {showArchived && (
            <div className="mt-3 space-y-2">
              {archived.map((card) => (
                <button
                  key={card.repo}
                  onClick={() => onOpenProject(card.repo)}
                  className="block w-full text-left text-xs p-2 rounded hover:bg-neutral-900 transition-colors text-neutral-400 hover:text-neutral-200"
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
