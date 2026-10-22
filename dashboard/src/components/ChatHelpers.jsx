import { useEffect, useState } from 'react'
import { AgentCard } from './AgentsPanel.jsx'

// A backstop only for the other Mac (#612): this Mac's helpers are pushed (their run logs land in the watched jobs
// folder and fire the 'agents' trigger); the other Mac's come from its webhook server, which has no push channel.
const REMOTE_POLL_MS = 30000

// Helpers a chat started with the Agent tool, on every Mac (#612), as the same rows Health shows its agents in.
export function ChatHelpersView({ data, now, onOpenTicket, onOpenMr }) {
  if (!data?.helpers?.length) return null
  const down = data.unreachable || []
  return (
    <div className="mb-4 max-w-3xl" data-testid="chat-helpers">
      <p className="mb-3 text-xs text-neutral-500">
        Helpers started from chats, on every Mac: what each is doing, or what it found.
        {down.length > 0 && ` Not reachable: ${down.join(', ')}.`}
      </p>
      <div className="flex flex-col gap-2">
        {data.helpers.map((h) => (
          <AgentCard key={`${h.machine}:${h.id}`} agent={h} now={now} onOpenTicket={onOpenTicket} onOpenMr={onOpenMr} />
        ))}
      </div>
    </div>
  )
}

export default function ChatHelpers({ onOpenTicket, onOpenMr }) {
  const [data, setData] = useState(null)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    let cancelled = false
    const refresh = () => window.api.activity.helpers().then((r) => !cancelled && setData(r)).catch(() => {})
    refresh()
    const off = window.api.triggers.on((t) => t.topic === 'agents' && refresh())
    const i = setInterval(refresh, REMOTE_POLL_MS)
    return () => { cancelled = true; off(); clearInterval(i) }
  }, [])

  const anyRunning = data?.helpers?.some((h) => h.status === 'running')
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), anyRunning ? 1000 : 30_000)
    return () => clearInterval(id)
  }, [anyRunning])

  return <ChatHelpersView data={data} now={now} onOpenTicket={onOpenTicket} onOpenMr={onOpenMr} />
}
