import { useEffect, useState } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'
import { projectIdOf } from '../lib/projects.js'

// Backstop only: triggers (window.api.triggers) drive refreshes; a poll that
// finds a change no trigger announced is logged as a gap.
const REFRESH_MS = 60_000

const COLUMN_STYLE = {
  backlog: 'border-neutral-700',
  ready: 'border-sky-700',
  blocked: 'border-red-700',
  progress: 'border-blue-600',
  review: 'border-amber-600',
  done: 'border-emerald-700'
}

function PrChip({ pr, repo, onOpenMr }) {
  return (
    <span
      role="button"
      tabIndex={0}
      title="Open in MR Review"
      onClick={(e) => {
        e.stopPropagation()
        onOpenMr(`${repo}#${pr.number}`)
      }}
      onKeyDown={(e) => e.key === 'Enter' && onOpenMr(`${repo}#${pr.number}`)}
      className="inline-flex items-center gap-1 rounded bg-amber-950 px-1.5 py-0.5 text-xs text-amber-300 hover:bg-amber-900"
    >
      PR #{pr.number}
      {pr.isDraft ? ' · draft' : ''}
      {pr.hasDevEvidence ? ' · dev env ✓' : ' · no dev evidence'}
    </span>
  )
}

function Card({ card, repo, onSelect, onOpenMr }) {
  return (
    <button
      onClick={() => onSelect(card)}
      className="w-full rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition-colors hover:border-neutral-600"
    >
      <p className="text-sm text-white">
        <span className="font-mono text-neutral-500">#{card.number}</span> {card.title}
      </p>
      <p className={`mt-1 text-xs ${card.reason && /fail|block/i.test(card.reason) ? 'text-red-400' : 'text-neutral-500'}`}>{card.reason}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        {card.owner === 'human' && <span className="rounded bg-sky-950 px-1.5 py-0.5 text-xs text-sky-300">human</span>}
        {card.prs.map((pr) => (
          <PrChip key={pr.number} pr={pr} repo={repo} onOpenMr={onOpenMr} />
        ))}
      </div>
    </button>
  )
}

function Column({ column, repo, onSelect, onOpenMr }) {
  return (
    <div className="flex w-72 shrink-0 flex-col">
      <div className={`mb-2 flex items-center justify-between border-b-2 pb-1 ${COLUMN_STYLE[column.id]}`}>
        <h3 className="text-xs font-medium uppercase tracking-wide text-neutral-300">{column.label}</h3>
        <span className="text-xs text-neutral-500">{column.cards.length}</span>
      </div>
      <div className="flex flex-col gap-2">
        {column.cards.map((card) => (
          <Card key={card.number} card={card} repo={repo} onSelect={onSelect} onOpenMr={onOpenMr} />
        ))}
        {column.cards.length === 0 && <p className="py-2 text-xs italic text-neutral-700">Nothing here</p>}
      </div>
    </div>
  )
}

function TicketDrilldown({ repo, card, onBack, onOpenMr }) {
  const [detail, setDetail] = useState(null)
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    window.api.boards
      .ticket(repo, card.number)
      .then(setDetail)
      .catch((e) => setError(cleanIpcError(e)))
    if (card.hasTimeline) window.api.activity.timeline(card.number).then(setEvents).catch(() => {})
  }, [repo, card.number, card.hasTimeline])

  return (
    <div className="max-w-3xl p-6">
      <button onClick={onBack} className="mb-4 text-sm text-neutral-400 hover:text-neutral-200">
        ← Back to board
      </button>
      <h2 className="text-lg font-semibold text-white">
        <span className="font-mono text-neutral-500">#{card.number}</span> {card.title}
      </h2>
      <p className="mt-1 text-sm text-neutral-400">{card.reason}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        {card.labels.map((l) => (
          <span key={l} className="rounded bg-neutral-800 px-1.5 py-0.5 text-xs text-neutral-400">
            {l}
          </span>
        ))}
        {card.prs.map((pr) => (
          <PrChip key={pr.number} pr={pr} repo={repo} onOpenMr={onOpenMr} />
        ))}
      </div>
      {error && <p className="mt-4 text-red-400">Failed to load ticket: {error}</p>}
      {detail && <pre className="mt-4 whitespace-pre-wrap rounded border border-neutral-800 bg-neutral-900 p-3 font-mono text-xs text-neutral-300">{detail.body || '(no description)'}</pre>}
      {events.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs uppercase tracking-wide text-neutral-500">Pipeline timeline</h3>
          {events.map((e, i) => (
            <p key={i} className={`border-l-2 border-neutral-800 py-1 pl-3 text-xs ${e.status === 'failed' ? 'text-red-400' : 'text-neutral-400'}`}>
              {e.stage} — {e.status} · {e.machine} · {new Date(e.timestamp).toLocaleString()}
              {e.detail ? ` · ${e.detail}` : ''}
            </p>
          ))}
        </div>
      )}
      {detail?.comments?.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs uppercase tracking-wide text-neutral-500">Comments ({detail.comments.length})</h3>
          {detail.comments.slice(-5).map((c, i) => (
            <pre key={i} className="mb-2 whitespace-pre-wrap rounded border border-neutral-800 p-2 font-mono text-xs text-neutral-400">
              {c.body}
            </pre>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ProjectBoard({ onOpenMr, onOpenDocs, nav }) {
  const [boards, setBoards] = useState(null)
  const [repo, setRepo] = useState(null)
  const [board, setBoard] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    window.api.boards
      .list()
      .then((list) => {
        setBoards(list)
        setRepo((cur) => cur || list[0]?.repo || null)
      })
      .catch((e) => setError(cleanIpcError(e)))
  }, [])

  // Deep link from Docs / MR Review: show that project's board (once per navigation).
  useEffect(() => {
    if (nav?.tab === 'activity' && nav.repo) {
      setRepo(nav.repo)
      setSelected(null)
    }
  }, [nav?.at])

  useEffect(() => {
    if (!repo) return
    let live = true
    // source tells the coverage guard whether a trigger or the backstop poll asked.
    const load = (source) =>
      window.api.boards
        .load(repo, source)
        .then((b) => live && (setBoard(b), setError(null)))
        .catch((e) => live && setError(cleanIpcError(e)))
    setBoard(null)
    load('initial')
    const id = setInterval(() => load('poll'), REFRESH_MS)
    const off = window.api.triggers.on((t) => t.topic === 'activity' && load('trigger'))
    return () => {
      live = false
      clearInterval(id)
      off()
    }
  }, [repo])

  if (boards === null && !error) return <div className="p-6 text-neutral-500">Loading…</div>
  if (boards && boards.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 text-center text-neutral-500">
        <p className="text-lg font-medium text-neutral-300">No project boards yet</p>
        <p className="max-w-md text-sm">A board appears when MARVIN starts working on a project (or run board_registry.py ensure owner/repo).</p>
      </div>
    )
  }
  const current = boards?.find((b) => b.repo === repo)

  if (selected) {
    return <TicketDrilldown repo={repo} card={selected} onBack={() => setSelected(null)} onOpenMr={onOpenMr} />
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {boards?.map((b) => (
          <button
            key={b.repo}
            onClick={() => setRepo(b.repo)}
            className={`rounded-full px-3 py-1 text-sm ${b.repo === repo ? 'bg-neutral-700 text-white' : 'text-neutral-400 hover:text-neutral-200'}`}
          >
            {b.name}
          </button>
        ))}
        {repo && (
          <button onClick={() => onOpenDocs?.(projectIdOf(repo))} className="ml-2 text-xs text-neutral-500 hover:text-neutral-200" title="Open this project's docs">
            Docs →
          </button>
        )}
        {current?.due && (
          <span className={`ml-auto text-xs ${current.dueHard ? 'text-amber-400' : 'text-neutral-500'}`}>
            {current.dueHard ? 'Hard' : 'Soft'} due {current.due}
          </span>
        )}
      </div>
      {error && <p className="mb-3 text-red-400">{error}</p>}
      {!board && !error && <p className="text-neutral-500">Loading {repo}…</p>}
      {board && (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {board.columns.map((c) => (
            <Column key={c.id} column={c} repo={repo} onSelect={setSelected} onOpenMr={onOpenMr} />
          ))}
        </div>
      )}
    </div>
  )
}
