import { useEffect, useState } from 'react'
import Markdown from './Markdown.jsx'

// The Support tab (ADR 0073), on both sides of a support link, showing the same conversation:
//   helper install: "Needs you" (the counter: what the helper's MARVIN couldn't solve) and "Handled by MARVIN", each
//                   with its outcome: verified on their Mac, answered but not applied yet, or fix failed.
//   helped install: "Replies waiting", "In progress" and "Done". An answer is carried out on this Mac with Apply with
//                   MARVIN, and counts only when its check passes here.
// Renders from the saved cache first; a change to it (support.py after any sync) re-reads it.

export const isIdea = (r) => String(r.state || '').startsWith('idea-')

export function groupRequests(all = [], role = 'helper') {
  const requests = all.filter((r) => !isIdea(r))
  const ideas = { id: 'ideas', title: 'Ideas', items: all.filter(isIdea), collapsed: role === 'helper' }
  return [...problemGroups(requests, role), ideas]
}

function problemGroups(requests, role) {
  if (role === 'helped') {
    return [
      { id: 'waiting', title: 'Replies waiting', items: requests.filter((r) => r.open && r.state === 'answered') },
      { id: 'progress', title: 'In progress', items: requests.filter((r) => r.open && r.state !== 'answered') },
      { id: 'done', title: 'Done', items: requests.filter((r) => !r.open), collapsed: true }
    ]
  }
  return [
    { id: 'needs-you', title: 'Needs you', items: requests.filter((r) => r.open && r.state === 'needs-you') },
    { id: 'handled', title: 'Handled by MARVIN', items: requests.filter((r) => !(r.open && r.state === 'needs-you')), collapsed: true }
  ]
}

// What happened to a request, in the words of whoever is looking. `tone` colours it.
const IDEA_OUTCOME = {
  helper: { 'idea-new': ['New idea', 'muted'], 'idea-proposal': ['In Proposals', 'muted'], 'idea-ticket': ['Ticket made', 'good'], 'idea-shipped': ['✓ Built', 'good'], 'idea-dismissed': ['Dismissed', 'muted'] },
  helped: { 'idea-new': ['Received', 'muted'], 'idea-proposal': ['Proposal', 'muted'], 'idea-ticket': ['Made a ticket ✓', 'good'], 'idea-shipped': ['✓ Built', 'good'], 'idea-dismissed': ['Not now', 'muted'] }
}

export function outcome(role, r) {
  const helper = role === 'helper'
  if (isIdea(r)) {
    const [text, tone] = IDEA_OUTCOME[helper ? 'helper' : 'helped'][r.state] || [r.state, 'muted']
    return { text, tone }
  }
  const v = r.verification
  if (r.state === 'verified' || (!r.open && v?.passed)) return { text: helper ? '✓ Verified on their Mac' : '✓ Fixed and verified', tone: 'good' }
  if (!r.open) return { text: 'Closed, not verified', tone: 'muted' }
  if (r.state === 'helper-trying' && v && v.passed === false) return { text: helper ? '↺ Fix failed, back to MARVIN' : '↺ Not fixed yet, trying again', tone: 'warn' }
  const open = {
    'trying-here': helper ? 'Their MARVIN is trying' : 'MARVIN is trying on this Mac',
    'helper-trying': helper ? 'Your MARVIN is on it' : "Sent to your helper's MARVIN",
    'needs-you': helper ? 'Needs you' : 'Waiting for your helper',
    answered: helper ? '… Answered, not applied yet' : 'Reply waiting'
  }
  return { text: open[r.state] || r.state, tone: r.state === 'needs-you' && helper ? 'warn' : 'muted' }
}

// Kept for the IT button's short list.
export const stateLabel = (role, r) => outcome(role, r).text

const TONE = { good: 'text-emerald-400', warn: 'text-amber-400', muted: 'text-neutral-500' }
const exitWord = (res) => (res == null ? '—' : res.exit === 0 ? 'ok' : `fail (${res.exit})`)

export function age(iso, now = Date.now()) {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const min = Math.max(0, Math.round((now - t) / 60000))
  if (min < 60) return `${min}m`
  if (min < 60 * 24) return `${Math.round(min / 60)}h`
  return `${Math.round(min / 1440)}d`
}

// The request's text and its attached diagnostics (filed by support.py inside a <details> block), shown apart.
export function splitDiagnostics(body = '') {
  const m = /<details>\s*<summary>[^<]*<\/summary>\s*```json\n([\s\S]*?)\n```\s*<\/details>/.exec(body)
  if (!m) return { text: body.trim(), diagnostics: null }
  return { text: (body.slice(0, m.index) + body.slice(m.index + m[0].length)).trim(), diagnostics: m[1] }
}

const who = (repo) => String(repo || '').split('/')[0]

// The helped person reads plain words (ADR 0073, audience): working / not working, with the technical detail tucked
// away. The helper sees the check itself.
const plain = (res) => (res == null ? 'not checked' : res.exit === 0 ? 'working' : 'not working')

export function CheckLine({ verification, role = 'helper' }) {
  if (!verification) return null
  if (role === 'helped') {
    return (
      <p className="pl-[8.5rem] text-xs text-neutral-500">
        Before the fix: {plain(verification.before)} · After: {plain(verification.after)}{verification.passed ? ' ✓' : ''}
      </p>
    )
  }
  return (
    <p className="pl-[8.5rem] text-xs text-neutral-500">
      check: <code className="text-neutral-400">{verification.check}</code> · before: {exitWord(verification.before)} · after: {exitWord(verification.after)}
    </p>
  )
}

export function RequestRow({ request, role, selected, onSelect, now }) {
  const o = outcome(role, request)
  return (
    <div>
      <button
        onClick={() => onSelect(request)}
        className={`flex w-full items-baseline gap-3 rounded-md px-3 py-2 text-left text-sm ${selected ? 'bg-neutral-800' : 'hover:bg-neutral-900'}`}
      >
        <span className="w-28 shrink-0 truncate text-neutral-500">{role === 'helper' ? who(request.repo) : `#${request.number}`}</span>
        <span className="flex-1 truncate text-neutral-100">{request.title}</span>
        <span className={`shrink-0 text-xs ${TONE[o.tone]}`}>{o.text}</span>
        <span className="w-8 shrink-0 text-right text-xs text-neutral-500">{age(request.updatedAt, now)}</span>
      </button>
      <CheckLine verification={request.verification} role={role} />
    </div>
  )
}

export function Verification({ v, role = 'helper' }) {
  const where = role === 'helped' ? 'this Mac' : 'their Mac'
  if (role === 'helped') {
    return (
      <div className={`mt-2 rounded border p-2 text-xs ${v.passed ? 'border-emerald-800 text-emerald-300' : 'border-amber-800 text-amber-300'}`}>
        <p className="font-semibold">{v.passed ? '✓ Fixed.' : '✗ Not fixed yet.'} Before: {plain(v.before)} · After: {plain(v.after)}</p>
        {!v.passed && <p className="mt-1 text-neutral-400">It's been sent back for another try. You don't need to do anything.</p>}
        <details className="mt-1 text-neutral-500">
          <summary className="cursor-pointer">Details</summary>
          <p className="mt-1">check: <code>{v.check}</code> · before: {exitWord(v.before)} · after: {exitWord(v.after)}</p>
          {v.after?.output && <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap">{v.after.output}</pre>}
        </details>
      </div>
    )
  }
  return (
    <div className={`mt-2 rounded border p-2 text-xs ${v.passed ? 'border-emerald-800 text-emerald-300' : 'border-amber-800 text-amber-300'}`}>
      <p className="font-semibold">{v.passed ? `✓ Check passed on ${where}` : `✗ Check still failing on ${where}`}</p>
      <p className="mt-1 text-neutral-400">check: <code>{v.check}</code></p>
      <p className="text-neutral-400">before: {exitWord(v.before)} · after: {exitWord(v.after)}</p>
      {v.after?.output && <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap text-neutral-400">{v.after.output}</pre>}
    </div>
  )
}

// Who wrote a comment, in the reader's words.
export function authorLabel(role, c) {
  if (role === 'helped') return { requester: 'You', helper: 'Your helper', 'helper-marvin': "Your helper's MARVIN (automatic)" }[c.by] || c.author
  return { requester: c.author, helper: 'You', 'helper-marvin': 'Your MARVIN (automatic)' }[c.by] || c.author
}

export function CheckNote({ c, role }) {
  if (!c.check) return null
  if (role === 'helped') {
    return (
      <details className="mt-2 text-xs text-neutral-400">
        <summary className="cursor-pointer">How we'll know it's fixed: {c.check_says || "MARVIN checks the problem is really gone"}</summary>
        <p className="mt-1 text-neutral-500">The check MARVIN runs: <code>{c.check}</code></p>
      </details>
    )
  }
  return <p className="mt-2 text-xs text-neutral-400">Check: <code>{c.check}</code>{c.check_says ? ` (${c.check_says})` : ''}</p>
}

export function Thread({ thread, role, busy, draft, setDraft, check, setCheck, onDraft, onSend, onResolve, onApply, onFollowup, message,
  preview = false, onPreview, onSendOriginal, onBack }) {
  const { text, diagnostics } = splitDiagnostics(thread.request.body)
  const open = thread.request.open
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-white">{thread.request.title}</h3>
        <a href={thread.request.url} className="text-xs text-neutral-500 hover:text-neutral-300">
          {thread.request.repo}#{thread.request.number}
        </a>
      </div>
      <div className="rounded-md border border-neutral-800 p-3">
        <p className="mb-1 text-xs text-neutral-500">{role === 'helped' ? 'You' : thread.request.author}</p>
        <Markdown content={text} />
        {diagnostics && (
          <details className="mt-2 text-xs text-neutral-400">
            <summary className="cursor-pointer">{role === 'helped' ? 'Technical details (sent automatically, no passwords)' : 'Diagnostics'}</summary>
            <pre className="mt-2 overflow-auto rounded bg-neutral-950 p-2">{diagnostics}</pre>
          </details>
        )}
      </div>
      {thread.comments.map((c, i) => (
        <div key={i} className="rounded-md border border-neutral-800 p-3">
          <p className="mb-1 text-xs text-neutral-500">{authorLabel(role, c)}</p>
          <Markdown content={c.body} />
          <CheckNote c={c} role={role} />
          {c.verification && <Verification v={c.verification} role={role} />}
        </div>
      ))}
      {isIdea(thread.request) && (
        <p className="text-xs text-neutral-500">
          {role === 'helper' ? 'This is an idea: decide it in MR Review → Proposals. The outcome is posted here automatically.' : 'Your helper decides ideas in their Proposals. What happens to it shows here, and you’ll get a notification.'}
        </p>
      )}
      {role === 'helper' && open && !isIdea(thread.request) && (
        <>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Reply…" rows={5}
            className="w-full rounded-md border border-neutral-700 bg-neutral-950 p-2 text-sm text-neutral-100" />
          <input value={check} onChange={(e) => setCheck(e.target.value)} placeholder="Check: a command that succeeds once it's fixed (optional)"
            className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1 font-mono text-xs text-neutral-200" />
          {preview ? (
            <>
              <p className="text-xs text-neutral-500">This is your reply rewritten for them. Every command is kept exactly as you wrote it. Edit it if you like.</p>
              <div className="flex gap-2">
                <button onClick={onSend} disabled={busy || !draft.trim()} className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-40">Send this</button>
                <button onClick={onSendOriginal} disabled={busy} className="rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-40">Send as I wrote it</button>
                <button onClick={onBack} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-neutral-500 hover:text-neutral-300 disabled:opacity-40">Back</button>
              </div>
            </>
          ) : (
            <div className="flex gap-2">
              <button onClick={onDraft} disabled={busy} className="rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-40">Draft with MARVIN</button>
              <button onClick={onPreview} disabled={busy || !draft.trim()} className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-40">Preview for them</button>
              <button onClick={onResolve} disabled={busy} className="rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-40">Resolve</button>
            </div>
          )}
        </>
      )}
      {role === 'helped' && open && !isIdea(thread.request) && (
        <>
          <button onClick={onApply} disabled={busy} className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-40">
            {thread.request.state === 'answered' ? 'Fix it with MARVIN' : 'Work on it with MARVIN'}
          </button>
          <p className="text-xs text-neutral-500">MARVIN shows you each step and asks before doing anything. It only marks this fixed once it has checked the problem is really gone.</p>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask a follow-up…" rows={3}
            className="w-full rounded-md border border-neutral-700 bg-neutral-950 p-2 text-sm text-neutral-100" />
          <button onClick={onFollowup} disabled={busy || !draft.trim()} className="rounded-md border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-40">Send follow-up</button>
        </>
      )}
      {message && <p className={`text-xs ${message.error ? 'text-red-400' : 'text-neutral-500'}`}>{message.text}</p>}
    </div>
  )
}

export default function SupportTab({ api = window.api.support, triggers = window.api.triggers, initial = null, now, nav = null }) {
  const [state, setState] = useState(initial)
  const [expanded, setExpanded] = useState({})
  const [selected, setSelected] = useState(null)
  const [thread, setThread] = useState(null)
  const [draft, setDraft] = useState('')
  const [check, setCheck] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [original, setOriginal] = useState(null) // the helper's own words while their rewrite is previewed

  useEffect(() => {
    const load = () => api.state().then(setState).catch(() => {})
    load()
    return triggers.on((t) => {
      if (t.topic !== 'support') return
      load()
      if (selected) loadThread(selected)
    })
  }, [selected])

  // Opened from the IT button or a notice: go straight to that request's thread.
  useEffect(() => {
    if (nav?.repo && nav?.number) open({ repo: nav.repo, number: nav.number })
  }, [nav?.at])

  async function loadThread(request) {
    const t = await api.act('thread', { repo: request.repo, number: request.number })
    if (t?.ok) setThread(t)
    else setMessage({ error: true, text: t?.error || "Couldn't load the request" })
  }

  function open(request) {
    setSelected(request)
    setThread(null)
    setDraft('')
    setCheck('')
    setOriginal(null)
    setMessage(null)
    loadThread(request)
  }

  async function act(cmd, extra = {}, done) {
    setBusy(true)
    setMessage(null)
    const r = await api.act(cmd, { repo: selected.repo, number: selected.number, ...extra })
    setBusy(false)
    if (!r?.ok) return setMessage({ error: true, text: r?.error || 'That didn’t work' })
    done?.(r)
  }

  if (!state) return <p className="p-6 text-sm text-neutral-500">Loading…</p>
  const role = state.role || 'helper'
  const groups = groupRequests(state.requests, role)
  const errors = Object.entries(state.errors || {})
  const isSel = (r) => selected && selected.repo === r.repo && selected.number === r.number

  return (
    <div className="grid h-full grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-6 p-6">
      <div className="space-y-4 overflow-auto">
        {groups.map((g) => {
          const shown = g.collapsed ? !!expanded[g.id] : expanded[g.id] !== false
          return (
            <section key={g.id}>
              <button onClick={() => setExpanded({ ...expanded, [g.id]: !shown })}
                className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400 hover:text-neutral-200">
                {g.title} ({g.items.length}) {g.collapsed ? (shown ? '▾' : '▸') : ''}
              </button>
              {shown && g.items.length === 0 && !g.collapsed && <p className="px-3 text-sm text-neutral-500">Nothing here.</p>}
              {shown && g.items.map((r) => (
                <RequestRow key={`${r.repo}#${r.number}`} request={r} role={role} now={now} onSelect={open} selected={isSel(r)} />
              ))}
            </section>
          )
        })}
        {errors.length > 0 && (
          <p className="px-3 text-xs text-amber-400">Couldn’t reach {errors.map(([repo]) => repo).join(', ')}. Showing the last saved state.</p>
        )}
      </div>
      <div className="overflow-auto">
        {!selected && <p className="text-sm text-neutral-500">Pick a request to see the conversation.</p>}
        {selected && !thread && !message && <p className="text-sm text-neutral-500">Loading the conversation…</p>}
        {selected && !thread && message && <p className="text-sm text-red-400">{message.text}</p>}
        {thread && (
          <Thread
            thread={thread}
            role={role}
            busy={busy}
            draft={draft}
            setDraft={setDraft}
            check={check}
            setCheck={setCheck}
            message={message}
            onDraft={() => act('draft', {}, (r) => { setDraft(r.text); setMessage({ text: 'Drafted by MARVIN. Edit it before sending.' }) })}
            preview={original !== null}
            onPreview={() => act('adapt', { text: draft }, (r) => { setOriginal(draft); setDraft(r.text) })}
            onBack={() => { setDraft(original ?? draft); setOriginal(null) }}
            onSendOriginal={() => act('reply', { text: original, check }, () => { setDraft(''); setCheck(''); setOriginal(null); setMessage({ text: 'Sent as you wrote it.' }); loadThread(selected) })}
            onSend={() => act('reply', { text: draft, check }, () => { setDraft(''); setCheck(''); setOriginal(null); setMessage({ text: 'Sent.' }); loadThread(selected) })}
            onResolve={() => act('resolve', {}, () => setMessage({ text: 'Resolved.' }))}
            onApply={() => act('open', {}, () => setMessage({ text: 'MARVIN is open in a new window. It will walk you through it, and the result shows up here.' }))}
            onFollowup={() => act('followup', { text: draft }, () => { setDraft(''); setMessage({ text: "Sent to your helper's MARVIN." }); loadThread(selected) })}
          />
        )}
      </div>
    </div>
  )
}
