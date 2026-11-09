import { useCallback, useEffect, useState } from 'react'

// Vitals > "Can MARVIN reach you?" (marvin#1123, ADR 0083): the one alert path's last alert, what each channel really
// did, and a button that sends a test alert. Sits at the top of Health, above Accounts.
const DOT = { reachable: 'bg-emerald-500', unreachable: 'bg-red-500', unknown: 'bg-neutral-600' }
const WORD = { reachable: 'Yes', unreachable: 'No: the last alert reached nothing', unknown: 'Not known yet: no alert sent' }
const CHANNEL = { desktop: 'Desktop', dashboard: 'Dashboard', phone: 'Phone' }

function ago(iso, now) {
  const t = Date.parse(iso || '')
  if (!Number.isFinite(t)) return ''
  const m = Math.max(0, Math.round((now - t) / 60_000))
  return m < 1 ? 'just now' : m < 60 ? `${m} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`
}

export function channelWord(result) {
  const r = String(result || '')
  if (r.startsWith('sent')) return { ok: true, text: r === 'sent' ? 'sent' : r.replace(/^sent\s*/, 'sent ') }
  if (r.startsWith('not set up')) return { ok: null, text: r }
  return { ok: false, text: r || 'no result' }
}

export function ReachView({ view, onTest, testing = false, note = null, now = Date.now() }) {
  const verdict = view?.verdict in WORD ? view.verdict : 'unknown'
  const last = view?.last
  return (
    <section data-testid="reach-row" data-verdict={verdict} className="mb-4 rounded-lg border border-neutral-800 bg-neutral-950 p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className={`h-2.5 w-2.5 rounded-full ${DOT[verdict]}`} />
        <h3 className="text-sm font-semibold text-white">Can MARVIN reach you?</h3>
        <span className="text-sm text-neutral-300">{WORD[verdict]}</span>
        <button onClick={onTest} disabled={testing || !onTest}
          className="ml-auto rounded-md border border-neutral-600 px-3 py-1 text-xs text-neutral-100 hover:bg-neutral-800 disabled:opacity-50">
          {testing ? 'Sending…' : 'Send a test alert'}
        </button>
      </div>
      {last && (
        <div className="mt-2 text-xs text-neutral-400">
          <p className="[overflow-wrap:anywhere]">Last alert {ago(last.at, now)}: <span className="text-neutral-200">{last.title || '(no title)'}</span></p>
          <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {Object.keys(CHANNEL).map((c) => {
              const w = channelWord(last.channels?.[c])
              return (
                <li key={c} data-channel={c} data-ok={String(w.ok)}>
                  <span className={w.ok ? 'text-emerald-400' : w.ok === false ? 'text-red-400' : 'text-neutral-500'}>{w.ok ? '✓' : w.ok === false ? '✕' : '–'}</span>{' '}
                  {CHANNEL[c]}: <span className="[overflow-wrap:anywhere]">{w.text}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      {(note || view?.problem) && <p className="mt-1 text-xs text-neutral-500 [overflow-wrap:anywhere]">{note || `Couldn't read the alert log: ${view.problem}`}</p>}
    </section>
  )
}

export default function ReachRow({ api = typeof window !== 'undefined' ? window.api?.alerts : null }) {
  const [view, setView] = useState(null)
  const [testing, setTesting] = useState(false)
  const [note, setNote] = useState(null)
  const load = useCallback(async () => {
    if (!api?.status) return
    try { setView(await api.status()) } catch (err) { setNote(String(err?.message || err).slice(0, 160)) }
  }, [api])
  useEffect(() => { load() }, [load])
  if (!api?.status) return null
  const onTest = async () => {
    setTesting(true)
    try {
      const r = await api.test()
      setNote(r?.delivered?.length ? `Test alert sent by ${r.delivered.join(', ')}.` : `The test alert reached nothing${r?.problem ? `: ${r.problem}` : ''}.`)
    } catch (err) {
      setNote(String(err?.message || err).slice(0, 160))
    } finally {
      setTesting(false)
      load()
    }
  }
  return <ReachView view={view} onTest={onTest} testing={testing} note={note} />
}
