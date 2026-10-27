import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { markdownComponents } from './Markdown.jsx'
import { safeUrl } from '../lib/issueBody.js'
import { sourceLabel, shortDate, fixed2, pickCurrent, progressOf, validNote, NOTE_CAP, excerptMarkdown } from '../lib/safety_reviews.js'

// Health ▸ Safety reviews (approved 2026-10-26, ADR 0015's missing review step): the quarantine one card at a time.
// Fine = approve, Fix it = modify with a note, Block = deny; each answer is recorded as a calibration label at once.
// Entry text is untrusted model output. It is rendered as markdown (Gil, 2026-10-26: "make it the most human readable")
// with the Docs tab's styles (Markdown.jsx markdownComponents) and the ticket body's URL sanitising (issueBody.safeUrl),
// and stricter than both: raw HTML shows as escaped text (react-markdown without rehype-raw), no image ever loads (an
// image is its alt text), and only http(s) and mailto links are links, opened outside the app like Docs links.

const EXTERNAL = /^(https?:|mailto:)/i
const entryComponents = {
  ...markdownComponents,
  a: ({ href, children }) =>
    href && EXTERNAL.test(href) ? (
      <a className="text-blue-400 hover:underline" href={href} target="_blank" rel="noreferrer noopener">{children}</a>
    ) : (
      <span>{children}</span>
    ),
  img: ({ alt }) => <span className="text-neutral-500">[image: {alt || 'no description'}]</span>
}

export function EntryMarkdown({ text }) {
  return (
    <div className="break-words text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={entryComponents} urlTransform={(url) => safeUrl(url) ?? ''}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

const BTN = 'rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-200 transition-colors hover:border-neutral-500 disabled:opacity-50'

export function ReviewCard({ entry, onAnswer, busy = false, initialExpanded = false, initialFixing = false }) {
  const [expanded, setExpanded] = useState(initialExpanded)
  const [fixing, setFixing] = useState(initialFixing)
  const [note, setNote] = useState('')
  const excerpt = useMemo(() => excerptMarkdown(entry.body), [entry.body])
  return (
    <article data-review-id={entry.id} className="flex flex-col gap-2 rounded-lg border border-neutral-800 bg-neutral-950/60 p-4">
      <h3 className="text-sm font-medium text-white">{sourceLabel(entry.loop)} · {shortDate(entry.date)}</h3>
      <p className="text-xs text-neutral-300">
        Risk {fixed2(entry.score)} <span className="text-neutral-500">(limit {fixed2(entry.tau)})</span>
      </p>
      {entry.reason && <p className="text-xs text-neutral-400">Why held: {entry.reason}</p>}
      {expanded ? (
        <div className="mt-2 max-h-[60vh] overflow-auto rounded bg-neutral-900 p-3">
          <EntryMarkdown text={entry.body} />
          {entry.truncated && <p className="text-neutral-500">…</p>}
        </div>
      ) : (
        <div className="mt-2 max-h-48 overflow-hidden">
          <EntryMarkdown text={excerpt.text} />
          {excerpt.cut && <p className="text-neutral-500">…</p>}
        </div>
      )}
      <div className="flex justify-end">
        <button type="button" onClick={() => setExpanded(!expanded)} className="text-xs text-neutral-400 hover:text-neutral-200">
          {expanded ? 'Show less ▴' : 'Show full item ▾'}
        </button>
      </div>
      <div className="mt-1 flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => onAnswer(entry.id, 'approve')} className={BTN}>Fine, let it through</button>
        <button type="button" disabled={busy} onClick={() => setFixing(!fixing)} className={`${BTN} ${fixing ? 'border-neutral-500' : ''}`}>Fix it</button>
        <button type="button" disabled={busy} onClick={() => onAnswer(entry.id, 'deny')} className={BTN}>Block</button>
      </div>
      {fixing && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (validNote(note)) onAnswer(entry.id, 'modify', note)
          }}
        >
          <textarea
            value={note}
            maxLength={NOTE_CAP}
            rows={3}
            onChange={(e) => setNote(e.target.value)}
            aria-label="What to change"
            placeholder="What to change"
            className="w-full rounded-md border border-neutral-700 bg-neutral-900 p-2 text-sm text-neutral-200"
          />
          <div className="flex justify-end">
            <button type="submit" disabled={busy || !validNote(note)} className={BTN}>Submit</button>
          </div>
        </form>
      )}
    </article>
  )
}

export function SafetyReviewsView({ data, answered, onAnswer, currentId = null, busy = false, error = null }) {
  if (!data) return <p className="text-sm text-neutral-500">Loading…</p>
  const entry = pickCurrent(data.entries, currentId)
  const p = progressOf(answered, Number.isInteger(data.pending) ? data.pending : (data.entries?.length ?? 0))
  return (
    <section className="mx-auto w-full max-w-2xl">
      <h2 className="mb-3 text-sm font-medium text-neutral-200">
        Safety reviews{p.total > 0 ? ` (${entry ? p.position : p.total} of ${p.total})` : ''}
      </h2>
      {(data.error || error) && <p className="mb-3 text-sm text-red-400">{data.error || error}</p>}
      {entry ? (
        // key: a new entry is a fresh card (closed, empty note)
        <ReviewCard key={entry.id} entry={entry} onAnswer={onAnswer} busy={busy} />
      ) : (
        !data.error && <p className="text-sm text-neutral-500">Nothing waiting for review.</p>
      )}
      {p.total > 0 && (
        <div className="mt-3 flex flex-col gap-1">
          <div className="h-1 w-full overflow-hidden rounded bg-neutral-800">
            <div className="h-full bg-neutral-400" style={{ width: `${Math.round((p.answered / p.total) * 100)}%` }} />
          </div>
          <p className="text-xs text-neutral-500">{p.answered} answered · {p.left} to go</p>
        </div>
      )}
      <p className="mt-2 text-xs text-neutral-500">Your answers teach the filter.</p>
    </section>
  )
}

// The Health tab's view: reads on open and when quarantine.md changes (the 'quarantine' trigger), answers through
// window.api.safety. The list itself is owned by HealthDashboard so its tab label can show the count.
export default function SafetyReviews({ data, reload }) {
  const [answered, setAnswered] = useState(0)
  const [currentId, setCurrentId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  useEffect(() => {
    const cur = pickCurrent(data?.entries, currentId)
    if (cur && cur.id !== currentId) setCurrentId(cur.id)
  }, [data])

  async function onAnswer(id, kind, text) {
    setBusy(true)
    setError(null)
    try {
      const res = await window.api.safety.answer(id, kind, text)
      if (res?.status === 'answered') setAnswered((n) => n + 1)
      // 'gone' / 'already-answered': answered on another Mac; the re-read below moves on to the next card.
      else if (res?.status !== 'gone' && res?.status !== 'already-answered') setError(`Not saved: ${res?.reason || res?.error || res?.status || 'no reply'}`)
      if (res?.status !== 'invalid' && res?.status !== 'failed' && res?.status !== 'busy') setCurrentId(null)
    } catch (err) {
      setError(`Not saved: ${err?.message || err}`)
    } finally {
      await reload()
      setBusy(false)
    }
  }

  return <SafetyReviewsView data={data} answered={answered} onAnswer={onAnswer} currentId={currentId} busy={busy} error={error} />
}
