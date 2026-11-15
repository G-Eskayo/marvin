import { useState, useRef, useEffect } from 'react'
import { redactText } from '../lib/redact.js'
import { createFadingMessage } from '../lib/fading_message.js'

export function composeOpenMessage(result) {
  if (!result || result.ok !== true) {
    return result?.error || 'Could not open a session'
  }
  if (result.focused) {
    return 'That ticket\u2019s chat was already open, so it\u2019s in front now'
  }
  const redactedDir = redactText(result.dir)
  return `Opened in ${redactedDir}`
}

// The MARVIN button (marvin#228): the main way in. Opens a ready MARVIN session in WezTerm on this Mac, in the
// ticket's own worktree, or at home with no ticket. Bare `claude` in a terminal stays the fallback.
export default function MarvinButton({ open = (request) => window.api.marvin.openSession(request) }) {
  const [panel, setPanel] = useState(false)
  const [ticket, setTicket] = useState('')
  const [state, setState] = useState({ busy: false, message: null, error: false })
  const timeoutRef = useRef(null)
  const scheduleFade = createFadingMessage()

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  async function launch(withTicket) {
    setState({ busy: true, message: null, error: false })
    const result = await open(withTicket ? { ticket: ticket.trim() } : {})
    const message = composeOpenMessage(result)
    const error = !result?.ok
    scheduleFade(setState, timeoutRef, { busy: false, message, error })
    if (result?.ok) {
      setPanel(false)
      setTicket('')
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setPanel(!panel)}
        title="Open a MARVIN session in WezTerm on this Mac"
        className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
      >
        MARVIN
      </button>
      {panel && (
        <div className="absolute right-0 z-20 mt-2 w-72 rounded-lg border border-neutral-700 bg-neutral-900 p-3 shadow-xl">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (ticket.trim()) launch(true)
            }}
          >
            <label className="mb-1 block text-xs text-neutral-400">Ticket (its own worktree)</label>
            <div className="flex gap-2">
              <input
                autoFocus
                value={ticket}
                onChange={(e) => setTicket(e.target.value)}
                placeholder="#228"
                className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100"
              />
              <button type="submit" disabled={state.busy || !ticket.trim()} className="rounded-md bg-blue-600 px-3 text-sm text-white disabled:opacity-40">
                Open
              </button>
            </div>
          </form>
          <button
            onClick={() => launch(false)}
            disabled={state.busy}
            className="mt-2 w-full rounded-md border border-neutral-700 py-1 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-40"
          >
            No ticket: open at home
          </button>
          {state.busy && <p className="mt-2 text-xs text-neutral-400">Opening…</p>}
        </div>
      )}
      {state.message && (
        <p className={`absolute right-0 mt-1 whitespace-nowrap text-xs ${state.error ? 'text-red-400' : 'text-neutral-500'}`}>
          {state.message}
        </p>
      )}
    </div>
  )
}
