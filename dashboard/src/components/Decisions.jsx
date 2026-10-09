import { useState } from 'react'

// The owner answers a PR's or ticket's Decisions section here (2026-10-09): big tappable options, a note per question,
// and text boxes for written answers. Submitting writes the answers into the description on GitHub (decisions_submit.js)
// and Approve unlocks once every required one is answered. Format: docs/agents/decisions-format.md.

// What the form starts with: whatever the description already holds.
export function initialDraft(questions) {
  return Object.fromEntries((questions || []).map((q) => [q.id, {
    choices: q.options.filter((o) => o.checked).map((o) => o.label),
    text: q.answer || '',
    note: q.note || ''
  }]))
}

export function isDraftAnswered(q, d) {
  if (q.kind === 'text') return !!(d?.text || '').trim()
  const n = (d?.choices || []).length
  return q.kind === 'single' ? n === 1 : n >= 1
}

export function missingRequired(questions, draft) {
  return (questions || []).filter((q) => q.required && !isDraftAnswered(q, draft[q.id])).map((q) => q.id)
}

// Only questions whose answer changed are sent, so an untouched one is never rewritten.
export function changedAnswers(questions, draft) {
  const start = initialDraft(questions)
  const out = {}
  for (const q of questions || []) {
    const a = draft[q.id] || {}
    const b = start[q.id]
    const same = (a.text || '') === b.text && (a.note || '') === b.note &&
      [...(a.choices || [])].sort().join('\u0000') === [...b.choices].sort().join('\u0000')
    if (!same) out[q.id] = q.kind === 'text' ? { text: a.text || '', note: a.note || '' } : { choices: a.choices || [], note: a.note || '' }
  }
  return out
}

export function toggleChoice(q, choices, label) {
  const has = choices.includes(label)
  if (q.kind === 'multi') return has ? choices.filter((c) => c !== label) : [...choices, label]
  return has ? [] : [label]
}

function Badge({ children, tone }) {
  const tones = { req: 'border-amber-700 text-amber-300', done: 'border-emerald-700 text-emerald-300', opt: 'border-neutral-700 text-neutral-400', multi: 'border-sky-800 text-sky-300' }
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] ${tones[tone]}`}>{children}</span>
}

function Question({ q, d, onChange, readOnly }) {
  const [showNote, setShowNote] = useState(!!d.note)
  const answered = isDraftAnswered(q, d)
  return (
    <fieldset className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-4" data-question={q.id}>
      <legend className="sr-only">{q.question}</legend>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <p className="text-base font-medium text-white">{q.question}</p>
        {q.required ? <Badge tone={answered ? 'done' : 'req'}>{answered ? 'Answered' : 'Required'}</Badge> : <Badge tone="opt">Optional</Badge>}
        {q.kind === 'multi' && <Badge tone="multi">Pick any</Badge>}
      </div>
      {q.kind === 'text' ? (
        <textarea
          value={d.text}
          disabled={readOnly}
          onChange={(e) => onChange({ ...d, text: e.target.value })}
          rows={2}
          placeholder="Type your answer"
          aria-label={q.question}
          className="w-full rounded-md border border-neutral-700 bg-neutral-900 p-2 text-sm text-neutral-100 placeholder:text-neutral-600 disabled:opacity-70"
        />
      ) : (
        <div className="flex flex-wrap gap-2" role={q.kind === 'multi' ? 'group' : 'radiogroup'} aria-label={q.question}>
          {q.options.map((o) => {
            const on = d.choices.includes(o.label)
            return (
              <button
                key={o.label}
                type="button"
                role={q.kind === 'multi' ? 'checkbox' : 'radio'}
                aria-checked={on}
                disabled={readOnly}
                onClick={() => onChange({ ...d, choices: toggleChoice(q, d.choices, o.label) })}
                className={`min-h-[44px] rounded-xl border-2 px-4 py-2 text-left text-sm font-medium transition-transform active:scale-95 disabled:cursor-default ${
                  on ? 'border-emerald-500 bg-emerald-500/15 text-emerald-200' : 'border-neutral-700 bg-neutral-900 text-neutral-200 hover:border-neutral-500'
                } ${readOnly && !on ? 'opacity-40' : ''}`}
              >
                {on && <span aria-hidden="true" className="mr-1.5">✓</span>}
                {o.label}
              </button>
            )
          })}
        </div>
      )}
      {q.kind !== 'text' && (showNote || d.note ? (
        <textarea
          value={d.note}
          disabled={readOnly}
          onChange={(e) => onChange({ ...d, note: e.target.value })}
          rows={1}
          placeholder="Add a note (optional)"
          aria-label={`Note for: ${q.question}`}
          className="mt-3 w-full rounded-md border border-neutral-800 bg-neutral-900 p-2 text-sm text-neutral-200 placeholder:text-neutral-600 disabled:opacity-70"
        />
      ) : !readOnly && (
        <button type="button" onClick={() => setShowNote(true)} className="mt-2 text-xs text-neutral-400 hover:text-neutral-200">+ Add a note</button>
      ))}
    </fieldset>
  )
}

export default function Decisions({ repo, number, decisions, onSubmitted, submit = (p) => window.api.decisions.submit(p) }) {
  const questions = decisions?.questions || []
  const [draft, setDraft] = useState(() => initialDraft(questions))
  const [editing, setEditing] = useState(() => (decisions?.pending || []).length > 0)
  const [status, setStatus] = useState({ state: 'idle' }) // idle | saving | saved | error
  if (!decisions?.present || !questions.length) return null

  const missing = missingRequired(questions, draft)
  const changes = changedAnswers(questions, draft)
  const dirty = Object.keys(changes).length > 0
  const pendingNow = decisions.pending || []

  async function onSubmit() {
    setStatus({ state: 'saving' })
    try {
      const r = await submit({ repo, number, answers: changes })
      setStatus({ state: 'saved', result: r })
      setEditing(false)
      onSubmitted?.(r)
    } catch (err) {
      setStatus({ state: 'error', message: String(err?.message || err).replace(/^Error invoking remote method '[^']+': (Error: )?/, '') })
    }
  }

  return (
    <div className="rounded-lg border-2 border-sky-800 bg-sky-950/20 p-4" data-decisions={pendingNow.length ? 'pending' : 'answered'}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="font-mono text-sm font-semibold text-white">Decisions</h4>
          <p className="text-xs text-neutral-400">
            {pendingNow.length
              ? `${pendingNow.length} to answer before you can approve.`
              : 'All required decisions are answered.'}
          </p>
        </div>
        {!editing && (
          <button type="button" onClick={() => setEditing(true)} className="rounded-md border border-neutral-700 px-3 py-1 text-sm text-neutral-200 hover:bg-neutral-800">
            Change
          </button>
        )}
      </div>
      <div className="flex flex-col gap-3">
        {questions.map((q) => (
          <Question key={q.id} q={q} d={draft[q.id]} readOnly={!editing} onChange={(d) => setDraft((prev) => ({ ...prev, [q.id]: d }))} />
        ))}
      </div>
      {editing && (
        <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
          {missing.length > 0 && (
            <p className="text-xs text-amber-300">Still to answer: {questions.filter((q) => missing.includes(q.id)).map((q) => q.question).join(' · ')}</p>
          )}
          <button
            type="button"
            onClick={onSubmit}
            disabled={!dirty || status.state === 'saving'}
            className="min-h-[44px] rounded-xl bg-emerald-600 px-5 py-2 text-sm font-semibold text-white transition-transform hover:bg-emerald-500 active:scale-95 disabled:opacity-40"
          >
            {status.state === 'saving' ? 'Saving…' : 'Submit decisions'}
          </button>
        </div>
      )}
      {status.state === 'saved' && (
        <p className="mt-3 text-right text-sm text-emerald-300">
          Saved to the description.{' '}
          {status.result?.commentUrl && <a href={status.result.commentUrl} target="_blank" rel="noreferrer" className="underline">Recorded on GitHub ↗</a>}
          {status.result?.commentError && <span className="block text-amber-300">{status.result.commentError}</span>}
          {status.result?.labelsChanged && <span className="block">The ticket is now ready for an agent.</span>}
        </p>
      )}
      {status.state === 'error' && <p className="mt-3 text-right text-sm text-red-400">Not saved: {status.message}</p>}
    </div>
  )
}
