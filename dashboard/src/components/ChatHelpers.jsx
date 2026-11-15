import { useEffect, useRef, useState } from 'react'
import { AgentCard } from './AgentsPanel.jsx'

// A backstop only for the other Mac (#612): this Mac's helpers are pushed (their run logs land in the watched jobs
// folder and fire the 'agents' trigger); the other Mac's come from its webhook server, which has no push channel.
const REMOTE_POLL_MS = 30000

export const HOME_CAP = 10
export const DISMISSED_KEY = 'chatHelpers.dismissed.v1'

// Generate a dismissal key for a helper
export function dismissKey(h) {
  return `${h.machine || 'local'}:${h.id}`
}

// Return only the visible helpers (not dismissed, respecting cap).
// Keep all running helpers, then fill remaining slots with other statuses up to cap.
export function visibleHelpers(helpers, dismissed, cap = HOME_CAP) {
  if (!Array.isArray(helpers)) return []
  const d = dismissed || {}
  const filtered = helpers.filter((h) => !d[dismissKey(h)])
  const running = filtered.filter((h) => h.status === 'running')
  const other = filtered.filter((h) => h.status !== 'running')
  // Keep all running, fill remaining cap slots with others
  const remaining = Math.max(0, cap - running.length)
  return [...running, ...other.slice(0, remaining)]
}

// Prune dismissed entries that are no longer in the helpers list, but preserve dismissed keys
// for unreachable machines (which aren't in the helpers array yet).
// Returns the same reference if no changes were made (prevents endless loops).
export function pruneDismissed(dismissed, helpers, unreachable = new Set()) {
  if (!dismissed || !Array.isArray(helpers)) return dismissed
  const currentKeys = new Set(helpers.map((h) => dismissKey(h)))
  const out = {}
  let changed = false

  for (const [key, value] of Object.entries(dismissed)) {
    const machine = key.split(':')[0]
    // Keep the entry if: (1) machine is unreachable (preserve for when it reconnects), OR
    // (2) the helper is still in the current list
    if (unreachable.has(machine) || currentKeys.has(key)) {
      out[key] = value
    } else {
      changed = true
    }
  }

  // If nothing changed, return the same reference (prevents re-render and effect re-run)
  if (!changed && Object.keys(out).length > 0) return dismissed

  return Object.keys(out).length === 0 ? null : out
}

// Helpers a chat started with the Agent tool, on every Mac (#612), as the same rows Health shows its agents in.
export function ChatHelpersView({ data, now, onOpenTicket, onOpenMr, dismissed, onDismiss }) {
  if (!data?.helpers?.length) return null
  const down = data.unreachable || []
  const visible = visibleHelpers(data.helpers, dismissed)
  if (visible.length === 0) return null

  return (
    <div className="mb-4 max-w-3xl" data-testid="chat-helpers">
      <p className="mb-3 text-xs text-neutral-500">
        Helpers started from chats, on every Mac: what each is doing, or what it found.
        {down.length > 0 && ` Not reachable: ${down.join(', ')}.`}
      </p>
      <div className="flex flex-col gap-2">
        {visible.map((h) => (
          <AgentCard
            key={`${h.machine}:${h.id}`}
            agent={h}
            now={now}
            onOpenTicket={onOpenTicket}
            onOpenMr={onOpenMr}
            onDismiss={h.status === 'crashed' && onDismiss ? () => onDismiss(dismissKey(h)) : undefined}
          />
        ))}
      </div>
    </div>
  )
}

function readSaved(storage, key) {
  try {
    const s = storage?.getItem(key)
    return s ? JSON.parse(s) : null
  } catch {
    return null
  }
}

function writeSaved(storage, key, value) {
  try {
    storage?.setItem(key, JSON.stringify(value))
  } catch {}
}

export default function ChatHelpers({ onOpenTicket, onOpenMr }) {
  const [data, setData] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [dismissed, setDismissed] = useState(() => readSaved(window?.localStorage, DISMISSED_KEY))
  const dismissedRef = useRef(dismissed)

  // Keep dismissedRef in sync with dismissed state, but this effect doesn't depend on dismissed
  // so it won't cause infinite loops.
  useEffect(() => {
    dismissedRef.current = dismissed
  }, [dismissed])

  // Main refresh effect: only runs once on mount and when manually triggered
  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      window.api.activity.helpers().then((r) => {
        if (!cancelled) {
          setData(r)
          // Prune stale dismissed entries, excluding unreachable machines
          if (r?.helpers) {
            const unreachable = new Set(r.unreachable || [])
            const pruned = pruneDismissed(dismissedRef.current, r.helpers, unreachable)
            if (pruned !== dismissedRef.current) {
              dismissedRef.current = pruned
              setDismissed(pruned)
              writeSaved(window?.localStorage, DISMISSED_KEY, pruned)
            }
          }
        }
      }).catch(() => {})
    }
    refresh()
    const off = window.api.triggers.on((t) => t.topic === 'agents' && refresh())
    const i = setInterval(refresh, REMOTE_POLL_MS)
    return () => { cancelled = true; off(); clearInterval(i) }
  }, [])

  const handleDismiss = (key) => {
    const next = { ...dismissed, [key]: true }
    setDismissed(next)
    writeSaved(window?.localStorage, DISMISSED_KEY, next)
  }

  const anyRunning = data?.helpers?.some((h) => h.status === 'running')
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), anyRunning ? 1000 : 30_000)
    return () => clearInterval(id)
  }, [anyRunning])

  return <ChatHelpersView data={data} now={now} onOpenTicket={onOpenTicket} onOpenMr={onOpenMr} dismissed={dismissed} onDismiss={handleDismiss} />
}
