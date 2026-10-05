import { useEffect, useMemo, useState } from 'react'
import { cleanIpcError } from '../lib/ipcError.js'

const TAG_STYLE = {
  type: 'bg-violet-950 text-violet-300',
  state: 'bg-neutral-800 text-neutral-400',
  claim: 'bg-sky-950 text-sky-300',
  priority: 'bg-orange-950 text-orange-300',
  other: 'bg-neutral-800 text-neutral-300'
}

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const monthLabel = (m) => {
  const [y, mm] = m.split('-')
  return MONTH_NAMES[Number(mm) - 1] ? `${MONTH_NAMES[Number(mm) - 1]} ${y}` : m
}

// Every ticket this project has finished: the record of where we have been. Completed work stays
// useful as reference (its docs, its PR, what it took), so it is searchable, not collapsed away.
export default function CompletedView({ repo, onSelect }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [tags, setTags] = useState(new Set())

  useEffect(() => {
    let live = true
    setData(null)
    setError(null)
    window.api.boards
      .completed(repo)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(cleanIpcError(e)))
    return () => {
      live = false
    }
  }, [repo])

  const q = query.trim().toLowerCase()
  const match = (item) =>
    (!q || `#${item.number} ${item.title} ${item.labels.join(' ')} ${item.pr?.title || ''}`.toLowerCase().includes(q)) && [...tags].every((t) => item.labels.includes(t))

  const tagCounts = useMemo(() => {
    const m = new Map()
    for (const item of data?.items || []) for (const t of item.tags) if (t.kind !== 'claim') m.set(t.name, { t, n: (m.get(t.name)?.n || 0) + 1 })
    return [...m.values()].sort((a, b) => b.n - a.n)
  }, [data])

  if (error) return <p className="text-red-400">{error}</p>
  if (!data) return <p className="text-neutral-500">Loading the finished work…</p>
  if (data.total === 0) return <p className="text-sm text-neutral-500">Nothing has been completed on this project yet.</p>

  const months = data.months.map((m) => ({ ...m, items: m.items.filter(match) })).filter((m) => m.items.length)
  const shown = months.reduce((n, m) => n + m.items.length, 0)
  return (
    <div className="max-w-4xl">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${data.total} completed tickets…`}
          className="w-72 rounded border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm text-white placeholder-neutral-600 focus:border-neutral-500 focus:outline-none"
        />
        <span className="text-xs text-neutral-600">
          {shown === data.total ? `${data.total} completed` : `${shown} of ${data.total}`}
        </span>
      </div>
      {tagCounts.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-1">
          {tagCounts.map(({ t, n }) => (
            <button
              key={t.name}
              onClick={() =>
                setTags((cur) => {
                  const next = new Set(cur)
                  next.has(t.name) ? next.delete(t.name) : next.add(t.name)
                  return next
                })
              }
              className={`rounded px-1.5 py-0.5 text-[10px] ${TAG_STYLE[t.kind]} ${tags.has(t.name) ? 'ring-1 ring-white/60' : 'opacity-80 hover:opacity-100'}`}
            >
              {t.name} · {n}
            </button>
          ))}
        </div>
      )}
      {months.length === 0 && <p className="text-sm text-neutral-500">Nothing matches.</p>}
      {months.map((m) => (
        <section key={m.month} className="mb-6">
          <h3 className="mb-1 border-b border-neutral-800 pb-1 text-xs uppercase tracking-wide text-neutral-500">
            {monthLabel(m.month)} · {m.items.length}
          </h3>
          {m.items.map((item) => (
            <button key={item.number} onClick={() => onSelect(item)} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-neutral-900">
              <span className="w-12 shrink-0 font-mono text-xs text-neutral-500">#{item.number}</span>
              <span className="min-w-0 flex-1 truncate text-sm text-neutral-200">{item.title}</span>
              <span className="hidden shrink-0 gap-1 md:flex">
                {item.tags.filter((t) => t.kind === 'type' || t.kind === 'priority' || t.kind === 'other').slice(0, 3).map((t) => (
                  <span key={t.name} className={`rounded px-1.5 py-0.5 text-[10px] ${TAG_STYLE[t.kind]}`}>
                    {t.name}
                  </span>
                ))}
              </span>
              {item.pr && (
                <a
                  href={item.pr.url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  title={item.pr.title}
                  className="shrink-0 rounded bg-emerald-950 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-900"
                >
                  PR #{item.pr.number} ↗
                </a>
              )}
              <span className="w-24 shrink-0 text-right text-[11px] text-neutral-600">
                {item.closedAt?.slice(0, 10)}
                {item.tookDays != null ? ` · ${item.tookDays}d` : ''}
              </span>
            </button>
          ))}
        </section>
      ))}
    </div>
  )
}
