import { useEffect, useState } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'
import { projectIdOf } from '../lib/projects.js'
import Markdown from './Markdown.jsx'
import Related, { useRelated } from './Related.jsx'
import CompletedView from './CompletedView.jsx'

// Backstop only: triggers (window.api.triggers) drive refreshes; a poll that
// finds a change no trigger announced is logged as a gap.
const REFRESH_MS = 60_000
const ARCHIVE_DAYS = 14 // must match ARCHIVE_AFTER_DAYS in electron/main/board.js

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

const TAG_STYLE = {
  type: 'bg-violet-950 text-violet-300',
  state: 'bg-neutral-800 text-neutral-400',
  claim: 'bg-sky-950 text-sky-300',
  priority: 'bg-orange-950 text-orange-300',
  other: 'bg-neutral-800 text-neutral-300'
}
// A state label that means "this needs somebody" should not look like furniture.
const tagClass = (t) => (t.name === 'needs-reengagement' || t.name === 'needs-info' ? 'bg-amber-950 text-amber-300' : TAG_STYLE[t.kind])

function Tag({ tag, active, onClick }) {
  return (
    <span
      role={onClick ? 'button' : undefined}
      onClick={
        onClick
          ? (e) => {
              e.stopPropagation()
              onClick(tag.name)
            }
          : undefined
      }
      className={`rounded px-1.5 py-0.5 text-[10px] ${tagClass(tag)} ${onClick ? 'cursor-pointer hover:brightness-125' : ''} ${active ? 'ring-1 ring-white/60' : ''}`}
    >
      {tag.name.startsWith('claimed:') ? `claimed · ${tag.name.slice(8)}` : tag.name}
    </span>
  )
}

function Card({ card, repo, onSelect, onOpenMr, activeTags, onTag }) {
  return (
    <button
      onClick={() => onSelect(card)}
      className="w-full rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition-colors hover:border-neutral-600"
    >
      <p className="text-sm text-white">
        <span className="font-mono text-neutral-500">#{card.number}</span> {card.title}
      </p>
      <p className={`mt-1 text-xs ${card.reason && /fail|block|stale|no activity/i.test(card.reason) ? 'text-red-400' : 'text-neutral-500'}`}>{card.reason}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {card.owner === 'human' && <span className="rounded bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-300">needs you</span>}
        {card.progress && (
          <span
            className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${card.progress.done === card.progress.total ? 'bg-emerald-950 text-emerald-300' : 'bg-neutral-800 text-neutral-300'}`}
            title={`${card.progress.done} of ${card.progress.total} checklist items done`}
          >
            ☑ {card.progress.done}/{card.progress.total}
          </span>
        )}
        {card.tags.filter((t) => !(t.kind === 'state' && (t.name === 'ready-for-agent' || t.name === 'ready-for-human'))).map((t) => (
          <Tag key={t.name} tag={t} active={activeTags.has(t.name)} onClick={onTag} />
        ))}
        {card.evidence && (
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] ${card.evidence.verdict === 'in-flight' ? 'bg-amber-950 text-amber-300' : 'bg-emerald-950 text-emerald-300'}`}
            title={card.evidence.items.map((e) => `${e.ref}: ${e.detail}`).join('\n')}
          >
            {card.evidence.verdict === 'in-flight' ? '⚠ work in flight' : '✓ commit mentions this'}
          </span>
        )}
        {card.blockedBy.map((n) => (
          <span key={n} className="rounded bg-red-950 px-1.5 py-0.5 font-mono text-[10px] text-red-300" title={`Blocked by #${n}`}>
            ⛔ #{n}
          </span>
        ))}
        {card.prs.map((pr) => (
          <PrChip key={pr.number} pr={pr} repo={repo} onOpenMr={onOpenMr} />
        ))}
        {card.ageDays != null && card.closedAt == null && <span className="ml-auto text-[10px] text-neutral-600">{card.ageDays}d old</span>}
      </div>
    </button>
  )
}

function Column({ column, repo, onSelect, onOpenMr, activeTags, onTag, onAllCompleted }) {
  const [showArchive, setShowArchive] = useState(false)
  const visible = column.cards.filter((c) => [...activeTags].every((t) => c.labels.includes(t)))
  const archive = column.archive || []
  return (
    <div className="flex w-72 shrink-0 flex-col">
      <div className={`mb-2 flex items-center justify-between border-b-2 pb-1 ${COLUMN_STYLE[column.id]}`}>
        <h3 className="text-xs font-medium uppercase tracking-wide text-neutral-300">{column.label}</h3>
        <span className="text-xs text-neutral-500">{activeTags.size ? `${visible.length} / ${column.cards.length}` : column.cards.length}</span>
      </div>
      {column.id === 'review' && column.cards.length > 0 && (
        <button onClick={() => onOpenMr?.()} className="-mt-1 mb-2 text-left text-[11px] text-amber-300 hover:text-amber-200" title="These are the same PRs MR Review lists">
          {column.cards.length} waiting in MR Review →
        </button>
      )}
      <div className="flex flex-col gap-2">
        {visible.map((card) => (
          <Card key={card.number} card={card} repo={repo} onSelect={onSelect} onOpenMr={onOpenMr} activeTags={activeTags} onTag={onTag} />
        ))}
        {visible.length === 0 && <p className="py-2 text-xs italic text-neutral-700">Nothing here</p>}
        {column.id === 'done' && (
          <button onClick={onAllCompleted} className="mt-1 text-left text-xs text-neutral-500 hover:text-neutral-300">
            All completed work →
          </button>
        )}
        {column.id === 'done' && archive.length > 0 && (
          <div className="mt-2">
            <button onClick={() => setShowArchive(!showArchive)} className="text-xs text-neutral-500 hover:text-neutral-300">
              {showArchive ? '▾' : '▸'} Archive · {archive.length} closed more than {ARCHIVE_DAYS} days ago
            </button>
            {showArchive && (
              <div className="mt-2 flex flex-col gap-1 opacity-70">
                {archive.map((card) => (
                  <button key={card.number} onClick={() => onSelect(card)} className="truncate rounded border border-neutral-900 px-2 py-1 text-left text-xs text-neutral-400 hover:border-neutral-700" title={card.title}>
                    <span className="font-mono text-neutral-600">#{card.number}</span> {card.title}
                    <span className="ml-1 text-neutral-700">{card.closedAt?.slice(0, 10)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Merge gate',
  merging: 'Merging',
  rebuilding: 'Rebuilding',
  done: 'Done'
}

const money = (usd) => (usd ? `$${usd.toFixed(usd < 0.01 ? 4 : 2)}` : '$0.00')
const when = (iso) => {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

// The ticket's pipeline history, stage by stage (what the old standalone "Pipeline log" listed for all
// tickets at once): where it got to, where it failed, on which machine, and what it cost.
function PipelineHistory({ events }) {
  const total = events.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
  const last = events[events.length - 1]
  return (
    <div className="mt-4">
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="text-xs uppercase tracking-wide text-neutral-500">Pipeline history</h3>
        <span className="font-mono text-xs text-neutral-400">
          now: {STAGE_LABEL[last.stage] || last.stage} ({last.status}) · total {money(total)}
        </span>
      </div>
      {events.map((e, i) => {
        const color = e.status === 'failed' ? 'text-red-400' : e.status === 'passed' ? 'text-emerald-400' : 'text-neutral-400'
        return (
          <div key={i} className="border-l-2 border-neutral-800 py-1.5 pl-4">
            <p className={`text-sm font-medium ${color}`}>
              {STAGE_LABEL[e.stage] || e.stage} — {e.status}
            </p>
            {e.detail && <p className="mt-0.5 whitespace-pre-wrap font-mono text-xs text-neutral-500">{e.detail}</p>}
            <p className="mt-0.5 text-xs text-neutral-600">
              {when(e.timestamp)} · {e.machine}
              {e.cost_usd != null ? ` · ${money(e.cost_usd)}` : ''}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function TicketDrilldown({ repo, card, onBack, onOpenMr, onOpenDocs, onOpenTicket }) {
  const [detail, setDetail] = useState(null)
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)
  const [ctx, setCtx] = useState(null)
  const rel = useRelated(() => window.api.relations.ticket(repo, card.number), [repo, card.number])

  useEffect(() => {
    window.api.relations.context(projectIdOf(repo)).then(setCtx).catch(() => {})
  }, [repo])

  useEffect(() => {
    window.api.boards
      .ticket(repo, card.number)
      .then(setDetail)
      .catch((e) => setError(cleanIpcError(e)))
    if (card.hasTimeline) window.api.activity.timeline(card.number, repo).then(setEvents).catch(() => {})
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
      {detail && (
        <div className="mt-4 rounded border border-neutral-800 bg-neutral-900 p-4 text-sm">
          {detail.body ? (
            <Markdown content={detail.body} ctx={ctx} onLink={(l) => (l.type === 'ticket' ? onOpenTicket?.(l.repo, l.number) : onOpenDocs?.(l.project, l.path))} />
          ) : (
            <p className="text-neutral-500">(no description)</p>
          )}
        </div>
      )}
      {events.length > 0 && <PipelineHistory events={events} />}
      <Related rel={rel} onTicket={onOpenTicket} onDoc={onOpenDocs} onPr={(r, n) => onOpenMr?.(`${r}#${n}`)} />
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

// Across ALL projects: where reviews and decisions are waiting on you, so the right board is one click away
// (the PRs in MR Review belong to whichever project they came from, not necessarily the board you have open).
function WaitingOnYou({ boards, onPick, onOpenMr, refreshKey }) {
  const [overview, setOverview] = useState(null)
  useEffect(() => {
    const load = () => window.api.activity.overview().then(setOverview).catch(() => {})
    load()
    const off = window.api.triggers.on((t) => (t.topic === 'activity' || t.topic === 'mr') && load())
    return off
  }, [refreshKey])
  if (!overview) return null
  const rows = (boards || [])
    .map((b) => ({ b, o: overview[b.repo] }))
    .filter(({ o }) => o && (o.review || o.needsYou))
  if (rows.length === 0) return null
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
      <span className="text-neutral-500">Waiting on you</span>
      {rows.map(({ b, o }) => (
        <button key={b.repo} onClick={() => onPick(b.repo)} className="rounded border border-neutral-800 px-2 py-1 text-neutral-300 hover:border-neutral-600">
          {b.name}
          {o.review > 0 && <span className="ml-2 text-amber-300">{o.review} in review</span>}
          {o.needsYou > 0 && <span className="ml-2 text-sky-300">{o.needsYou} need you</span>}
        </button>
      ))}
      <button onClick={() => onOpenMr?.()} className="text-neutral-500 hover:text-neutral-200">
        MR Review →
      </button>
    </div>
  )
}

// Every tag on the board with how many cards carry it; click to filter (all selected tags must match).
function TagBar({ board, activeTags, onTag, onClear }) {
  const counts = new Map()
  for (const c of board.columns) for (const card of c.cards) for (const t of card.tags) counts.set(t.name, { tag: t, n: (counts.get(t.name)?.n || 0) + 1 })
  const tags = [...counts.values()].filter(({ tag }) => tag.kind !== 'claim').sort((a, b) => b.n - a.n)
  if (tags.length === 0) return null
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1">
      <span className="mr-1 text-[11px] text-neutral-600">Filter by tag</span>
      {tags.map(({ tag, n }) => (
        <button key={tag.name} onClick={() => onTag(tag.name)} className={`rounded px-1.5 py-0.5 text-[10px] ${tagClass(tag)} ${activeTags.has(tag.name) ? 'ring-1 ring-white/60' : 'opacity-80 hover:opacity-100'}`}>
          {tag.name} · {n}
        </button>
      ))}
      {activeTags.size > 0 && (
        <button onClick={onClear} className="ml-2 text-[11px] text-neutral-400 hover:text-white">
          clear
        </button>
      )}
    </div>
  )
}

export default function ProjectBoard({ onOpenMr, onOpenDocs, onOpenTicket, nav }) {
  const [boards, setBoards] = useState(null)
  const [repo, setRepo] = useState(null)
  const [board, setBoard] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [activeTags, setActiveTags] = useState(new Set())
  const [view, setView] = useState('board') // 'board' | 'completed'
  const toggleTag = (name) =>
    setActiveTags((cur) => {
      const next = new Set(cur)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })

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
  const [pendingTicket, setPendingTicket] = useState(null)
  useEffect(() => {
    if (nav?.tab === 'activity' && nav.repo) {
      setRepo(nav.repo)
      setSelected(null)
      setView('board')
      setPendingTicket(nav.ticketNumber || null)
    }
  }, [nav?.at])

  const cardFor = (number) =>
    board?.columns.flatMap((c) => [...c.cards, ...(c.archive || [])]).find((k) => k.number === number) || {
      number,
      title: `#${number}`,
      labels: [],
      tags: [],
      prs: [],
      blockedBy: [],
      reason: '',
      hasTimeline: false
    }

  // Open a ticket from a link: same project stays here, another project goes through the app's navigation.
  const openTicket = (r, n) => (r === repo ? setSelected(cardFor(n)) : onOpenTicket?.(r, n))

  // A deep link names a ticket: show it once its board has loaded.
  useEffect(() => {
    if (pendingTicket && board) {
      setSelected(cardFor(pendingTicket))
      setPendingTicket(null)
    }
  }, [pendingTicket, board])

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
  const working = (boards || []).filter((b) => b.status !== 'dormant' && b.status !== 'archived')
  const dormant = (boards || []).filter((b) => b.status === 'dormant' || b.status === 'archived')
  const boardIsEmpty = board && board.columns.every((c) => c.cards.length === 0 && !(c.archive || []).length)

  if (selected) {
    return <TicketDrilldown repo={repo} card={selected} onBack={() => setSelected(null)} onOpenMr={onOpenMr} onOpenDocs={onOpenDocs} onOpenTicket={openTicket} />
  }

  return (
    <div className="p-6">
      <WaitingOnYou boards={boards} onPick={(r) => { setRepo(r); setView('board'); setSelected(null) }} onOpenMr={onOpenMr} refreshKey={repo} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {working.map((b) => (
          <button
            key={b.repo}
            onClick={() => setRepo(b.repo)}
            className={`rounded-full px-3 py-1 text-sm ${b.repo === repo ? 'bg-neutral-700 text-white' : 'text-neutral-400 hover:text-neutral-200'}`}
          >
            {b.name}
          </button>
        ))}
        {dormant.length > 0 && (
          <select
            value={dormant.some((b) => b.repo === repo) ? repo : ''}
            onChange={(e) => e.target.value && setRepo(e.target.value)}
            className="rounded-full border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-500"
            title="Boards of projects nobody has touched in months: kept, just out of the way"
          >
            <option value="">Dormant boards ({dormant.length})</option>
            {dormant.map((b) => (
              <option key={b.repo} value={b.repo}>
                {b.name} ({b.status})
              </option>
            ))}
          </select>
        )}
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
      <div className="mb-3 flex gap-1">
        {[['board', 'Board'], ['completed', 'Completed']].map(([id, label]) => (
          <button
            key={id}
            onClick={() => setView(id)}
            className={`rounded px-3 py-1 text-xs ${view === id ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            {label}
          </button>
        ))}
      </div>
      {view === 'completed' && repo && <CompletedView
          repo={repo}
          onSelect={(item) =>
            // a completed item is a finished card: give the drill-down the same shape a board card has
            setSelected({
              number: item.number,
              title: item.title,
              labels: item.labels,
              tags: item.tags,
              blockedBy: [],
              reason: `Completed ${item.closedAt?.slice(0, 10) || ''}${item.tookDays != null ? `, took ${item.tookDays} days` : ''}`,
              prs: item.pr ? [{ number: item.pr.number, title: item.pr.title, url: item.pr.url, isDraft: false, hasDevEvidence: false }] : [],
              hasTimeline: repo === 'G-Eskayo/marvin',
              closedAt: item.closedAt
            })
          }
        />}
      {error && <p className="mb-3 text-red-400">{error}</p>}
      {view === 'board' && !board && !error && <p className="text-neutral-500">Loading {repo}…</p>}
      {view === 'board' && boardIsEmpty && (
        <p className="mb-3 rounded border border-neutral-800 bg-neutral-900 p-3 text-sm text-neutral-400">
          No tickets yet for this project. File them with <code className="text-neutral-200">/to-issues</code> and they appear here by themselves.
        </p>
      )}
      {view === 'board' && board && <TagBar board={board} activeTags={activeTags} onTag={toggleTag} onClear={() => setActiveTags(new Set())} />}
      {view === 'board' && board && (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {board.columns.map((c) => (
            <Column key={c.id} column={c} repo={repo} onSelect={setSelected} onOpenMr={onOpenMr} activeTags={activeTags} onTag={toggleTag} onAllCompleted={() => setView('completed')} />
          ))}
        </div>
      )}
    </div>
  )
}
