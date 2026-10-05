import { useEffect, useState } from 'react'

const AGENT_INFO = {
  prioritize: ['Prioritize', 'Sets priority:p0 to p3 from what a ticket unblocks, deadlines, bugs and age. Leaves priorities a person set alone.'],
  triage: ['Triage', 'Sorts untriaged tickets into ready-for-agent, ready-for-human or needs-info (no model, no tokens). Never touches PRDs or claimed tickets.'],
  stale_claims: ['Release stale claims', 'Releases a claim nobody has touched for 2 days when no branch or PR is in flight for it. A held or pinned ticket is never released.'],
  refeed: ['Re-queue denied tickets', 'A ticket you denied (needs-reengagement) goes back to the queue with its feedback; after two tries it goes to a person.']
}
const ORDER = ['prioritize', 'triage', 'stale_claims', 'refeed']

function ago(iso) {
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000)
  return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min ago` : `${Math.round(s / 3600)} h ago`
}

function AgentSection({ agent, rows, mode, pinned }) {
  const [open, setOpen] = useState(false)
  const [all, setAll] = useState(false)
  const [title, blurb] = AGENT_INFO[agent]
  const shown = all ? rows : rows.slice(0, 8)
  return (
    <div className="rounded border border-neutral-800">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <span className="text-sm text-neutral-200">{title}</span>
        <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">{mode === 'act' ? 'acting' : pinned ? 'proposal-only (pinned)' : 'proposing'}</span>
        <span className="ml-auto text-xs text-neutral-500">{rows.length} ticket{rows.length === 1 ? '' : 's'}</span>
        <span className="text-xs text-neutral-600">{open ? 'hide' : 'review'}</span>
      </button>
      {open && (
        <div className="border-t border-neutral-900 px-3 py-2">
          <p className="mb-2 text-[11px] text-neutral-600">{blurb}</p>
          {shown.map((r) => (
            <div key={`${r.repo}#${r.number}`} className="py-1 text-xs">
              <p className="truncate text-neutral-300">
                <span className="font-mono text-neutral-500">{r.repo.split('/')[1]} #{r.number}</span> {r.title}
              </p>
              <p className="text-neutral-500">
                {r.changes.map((c, i) => (
                  <span key={i} className={`mr-1.5 rounded px-1 py-px font-mono text-[10px] ${c.startsWith('−') ? 'bg-red-950 text-red-300' : c.startsWith('+') ? 'bg-emerald-950 text-emerald-300' : 'bg-neutral-800 text-neutral-400'}`}>
                    {c}
                  </span>
                ))}
                {r.why}
              </p>
            </div>
          ))}
          {rows.length > 8 && (
            <button onClick={() => setAll(!all)} className="mt-1 text-xs text-neutral-500 hover:text-neutral-300">
              {all ? 'Show fewer' : `Show all ${rows.length}`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// Review surface for the ticket agents: what they would change (or just changed) on your tickets.
export default function TicketAgentsPanel() {
  const [data, setData] = useState(undefined)
  useEffect(() => {
    const load = () => window.api.health.ticketAgents().then(setData).catch(() => setData(null))
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [])
  if (data === undefined) return null
  if (data === null) {
    return (
      <div className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <p className="text-sm font-medium text-white">Ticket agents</p>
        <p className="mt-1 text-xs text-neutral-500">Have not run yet. They run with the hourly ticket scan and start by only proposing changes here.</p>
      </div>
    )
  }
  const acting = Object.values(data.byAgent).some((a) => a.mode === 'act')
  return (
    <div className="mb-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-white">Ticket agents</p>
        <p className="text-xs text-neutral-600">last pass {ago(data.generatedAt)}</p>
      </div>
      <p className="mt-1 text-xs text-neutral-400">
        {data.mode === 'off'
          ? 'Switched off.'
          : acting
            ? 'Acting now where allowed; everything is in the audit log (~/.claude/logs/ticket-agent-actions.jsonl) with what each ticket looked like before.'
            : `Only proposing: nothing below has been changed on GitHub yet.${data.actAfter ? ` Prioritize and triage start acting on ${data.actAfter}.` : ''}`}{' '}
        Releasing stale claims and re-queueing denied tickets stay proposal-only until you change them in <code className="text-neutral-300">config/ticket_agents.json</code>. Label a ticket <code className="text-neutral-300">pinned</code> and no agent touches it.
      </p>
      <div className="mt-3 flex flex-col gap-2">
        {ORDER.map((a) => {
          const rows = data.grouped[a] || []
          const info = data.byAgent[a]
          if (!info) return null
          return rows.length ? (
            <AgentSection key={a} agent={a} rows={rows} mode={info.mode} pinned={data.pinned[a] === 'propose'} />
          ) : (
            <p key={a} className="px-1 text-xs text-neutral-600">
              {AGENT_INFO[a][0]}: nothing to do right now.
            </p>
          )
        })}
      </div>
    </div>
  )
}
