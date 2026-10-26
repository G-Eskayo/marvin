import { useEffect, useState } from 'react'
import { stateLabel } from './SupportTab.jsx'

// The IT button (ADR 0073), on a helped install: say what's wrong and it goes to the helper's MARVIN, headless: no
// window opens here. What that can't solve goes to the helper in person.
// The dot means a reply is waiting; a request opens its conversation in the Support tab. Renders from the saved cache; a change to it re-reads it.
export default function ItButton({ api = window.api.support, triggers = window.api.triggers, initial = null, initialOpen = false, onOpen = () => {} }) {
  const [state, setState] = useState(initial)
  const [panel, setPanel] = useState(initialOpen)
  const [text, setText] = useState('')
  const [mode, setMode] = useState('problem') // 'problem' | 'idea'
  const [status, setStatus] = useState({ busy: false, message: null, error: false })

  useEffect(() => {
    const load = () => api.state().then(setState).catch(() => {})
    load()
    return triggers.on((t) => t.topic === 'support' && load())
  }, [])

  async function sendIdea() {
    setStatus({ busy: true, message: 'Sending your idea…', error: false })
    const sent = await api.act('idea', { text })
    if (!sent?.ok) return setStatus({ busy: false, message: sent?.error || 'Could not send it', error: true })
    setText('')
    setStatus({ busy: false, message: 'Sent. You’ll see what happens to it under Support → Ideas.', error: false })
  }

  async function getHelp() {
    setStatus({ busy: true, message: 'Filing your request…', error: false })
    const filed = await api.act('file', { text })
    if (!filed?.ok) return setStatus({ busy: false, message: filed?.error || 'Could not file it', error: true })
    setText('')
    // Headless (Gil, 2026-10-26): nothing opens here. The helper's MARVIN takes it; the answer arrives as a notice.
    setStatus({ busy: false, message: "Sent. Your helper's MARVIN is on it, and you'll get a notification when there's an answer.", error: false })
  }

  // A request opens its conversation in the Support tab, where the answer and the check results are.
  function show(r) {
    setPanel(false)
    onOpen(r)
  }

  const waiting = state?.badge || 0
  const all = state?.requests || []
  const requests = all.filter((r) => !String(r.state).startsWith('idea-')).slice(0, 6)
  const ideas = all.filter((r) => String(r.state).startsWith('idea-')).slice(0, 4)

  return (
    <div className="relative">
      <button
        onClick={() => setPanel(!panel)}
        title={waiting ? `${waiting} repl${waiting === 1 ? 'y' : 'ies'} waiting` : 'Get help with MARVIN'}
        className="flex items-center gap-1.5 rounded-md border border-neutral-700 px-3 py-1.5 text-sm font-medium text-neutral-200 hover:bg-neutral-800"
      >
        IT
        {waiting > 0 && <span className="h-2 w-2 rounded-full bg-blue-500" />}
      </button>
      {panel && (
        <div className="absolute right-0 z-20 mt-2 w-80 rounded-lg border border-neutral-700 bg-neutral-900 p-3 shadow-xl">
          <div className="mb-2 flex gap-3 text-xs text-neutral-300" role="radiogroup">
            {[['problem', "Something's wrong"], ['idea', 'I have an idea']].map(([id, label]) => (
              <label key={id} className="flex items-center gap-1">
                <input type="radio" name="it-mode" checked={mode === id} onChange={() => setMode(id)} /> {label}
              </label>
            ))}
          </div>
          <label className="mb-1 block text-xs text-neutral-400">{mode === 'idea' ? "What's the idea?" : "What's wrong?"}</label>
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder={mode === 'idea' ? 'A skill that turns my rough notes into a good prompt' : 'The dashboard is blank after the update'}
            className="w-full rounded-md border border-neutral-700 bg-neutral-950 p-2 text-sm text-neutral-100"
          />
          <div className="mt-2 flex justify-end">
            <button onClick={mode === 'idea' ? sendIdea : getHelp} disabled={status.busy || !text.trim()} className="rounded-md bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-40">
              {mode === 'idea' ? 'Send idea' : 'Get help'}
            </button>
          </div>
          {status.message && <p className={`mt-2 text-xs ${status.error ? 'text-red-400' : 'text-neutral-400'}`}>{status.message}</p>}
          {requests.length > 0 && (
            <div className="mt-3 border-t border-neutral-800 pt-2">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">My requests</p>
              {requests.map((r) => (
                <button
                  key={`${r.repo}#${r.number}`}
                  onClick={() => show(r)}
                  title="See the conversation"
                  className="flex w-full items-baseline gap-2 rounded px-1 py-1 text-left text-sm hover:bg-neutral-800"
                >
                  <span className="flex-1 truncate text-neutral-200">{r.title}</span>
                  <span className="shrink-0 text-xs text-neutral-500">{stateLabel('helped', r)}</span>
                  {r.open && r.state === 'answered' && <span className="h-2 w-2 shrink-0 rounded-full bg-blue-500" />}
                </button>
              ))}
            </div>
          )}
          {ideas.length > 0 && (
            <div className="mt-3 border-t border-neutral-800 pt-2">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-500">My ideas</p>
              {ideas.map((r) => (
                <button
                  key={`${r.repo}#${r.number}`}
                  onClick={() => show(r)}
                  title="See the conversation"
                  className="flex w-full items-baseline gap-2 rounded px-1 py-1 text-left text-sm hover:bg-neutral-800"
                >
                  <span className="flex-1 truncate text-neutral-200">{r.title}</span>
                  <span className="shrink-0 text-xs text-neutral-500">{stateLabel('helped', r)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
