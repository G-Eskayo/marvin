import { useEffect, useState } from 'react'

const COLUMN_STYLE = {
  done: 'bg-emerald-950 text-emerald-300',
  review: 'bg-amber-950 text-amber-300',
  progress: 'bg-blue-950 text-blue-300',
  blocked: 'bg-red-950 text-red-300',
  ready: 'bg-sky-950 text-sky-300',
  backlog: 'bg-neutral-800 text-neutral-400'
}
const COLUMN_LABEL = { done: 'done', review: 'in review', progress: 'in progress', blocked: 'blocked', ready: 'ready', backlog: 'backlog' }

function StatusChip({ item }) {
  const col = item.column
  const text = col ? COLUMN_LABEL[col] : item.state === 'CLOSED' || item.state === 'MERGED' ? 'closed' : item.state === 'OPEN' ? 'open' : null
  if (!text) return null
  return <span className={`shrink-0 rounded px-1 py-px text-[10px] ${COLUMN_STYLE[col] || 'bg-neutral-800 text-neutral-400'}`}>{text}</span>
}

function Row({ relation, children, onClick, status }) {
  return (
    <button onClick={onClick} className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-neutral-900">
      <span className="w-28 shrink-0 text-[11px] text-neutral-600">{relation}</span>
      <span className="min-w-0 flex-1 truncate text-neutral-300">{children}</span>
      {status}
    </button>
  )
}

// What this ticket / doc / MR is related to, derived from the text of all of them (relations.js).
// Clicking an item goes to it: a doc opens in Docs, a ticket on its board, an MR in MR Review.
export function useRelated(loader, deps) {
  const [rel, setRel] = useState(null)
  useEffect(() => {
    let live = true
    setRel(null)
    loader()
      .then((r) => live && setRel(r))
      .catch(() => live && setRel({ docs: [], tickets: [], prs: [] }))
    return () => {
      live = false
    }
  }, deps)
  return rel
}

export default function Related({ rel, onTicket, onDoc, onPr, hide = [] }) {
  if (!rel) return <p className="mt-6 text-xs text-neutral-600">Finding related items…</p>
  const empty = !rel.docs.length && !rel.tickets.length && !rel.prs.length
  return (
    <section className="mt-8 max-w-3xl border-t border-neutral-800 pt-4">
      <h3 className="text-xs uppercase tracking-wide text-neutral-500">Related</h3>
      {empty && <p className="mt-2 text-xs text-neutral-600">Nothing references this yet, and it references nothing else. Mention a ticket as #12 or an ADR as "ADR 0033" and the link appears here.</p>}
      {!hide.includes('docs') && rel.docs.length > 0 && (
        <div className="mt-2">
          <p className="px-2 text-[11px] text-neutral-600">Docs</p>
          {rel.docs.map((d) => (
            <Row key={`${d.project}/${d.path}`} relation={d.relation} onClick={() => onDoc?.(d.project, d.path)}>
              <span className="text-neutral-200">{d.label}</span> <span className="text-neutral-600">{d.project}</span>
            </Row>
          ))}
        </div>
      )}
      {rel.tickets.length > 0 && (
        <div className="mt-2">
          <p className="px-2 text-[11px] text-neutral-600">Tickets</p>
          {rel.tickets.map((t) => (
            <Row key={`${t.repo}#${t.number}`} relation={t.relation} onClick={() => onTicket?.(t.repo, t.number)} status={<StatusChip item={t} />}>
              <span className="font-mono text-neutral-500">#{t.number}</span> {t.title}
            </Row>
          ))}
        </div>
      )}
      {rel.prs.length > 0 && (
        <div className="mt-2">
          <p className="px-2 text-[11px] text-neutral-600">Pull requests</p>
          {rel.prs.map((p) => (
            <Row key={`${p.repo}#${p.number}`} relation={p.relation} onClick={() => onPr?.(p.repo, p.number)} status={<StatusChip item={p} />}>
              <span className="font-mono text-neutral-500">#{p.number}</span> {p.title}
            </Row>
          ))}
        </div>
      )}
    </section>
  )
}
