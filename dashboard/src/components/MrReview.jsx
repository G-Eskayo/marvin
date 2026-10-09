import { cleanIpcError } from '../lib/ipcError.js'
import { useEffect, useRef, useState } from 'react'
import { describePrState } from '../lib/prState.js'
import MrDetail from './MrDetail.jsx'
import { StageStrip } from './StageStrip.jsx'

const MR_LIST_REFRESH_MS = 120000

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-neutral-500">
      <p className="text-lg font-medium text-neutral-300">No MRs waiting on you</p>
      <p className="max-w-md text-sm">Every open PR on the repo shows up here — there just aren't any open right now.</p>
    </div>
  )
}

function VerdictBadge({ verdict }) {
  if (!verdict) return null
  const good = verdict.toLowerCase().includes('improve')
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        good ? 'bg-green-950 text-green-400' : 'bg-amber-950 text-amber-400'
      }`}
    >
      {verdict}
    </span>
  )
}

// Exported so MrDetail.jsx can render the same table without duplicating it.
export function EvidenceTable({ metrics }) {
  if (metrics.length === 0) {
    return <p className="text-sm text-neutral-500">No metrics table attached.</p>
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-neutral-500">
          <th className="pb-1 pr-4 font-normal">Metric</th>
          <th className="pb-1 pr-4 font-normal">Baseline</th>
          <th className="pb-1 pr-4 font-normal">Current</th>
          <th className="pb-1 font-normal">Delta</th>
        </tr>
      </thead>
      <tbody className="font-mono text-neutral-200">
        {metrics.map((m) => (
          <tr key={m.name}>
            <td className="pr-4 py-0.5">{m.name}</td>
            <td className="pr-4 py-0.5 text-neutral-400">{m.baseline}</td>
            <td className="pr-4 py-0.5">{m.current}</td>
            <td className={`py-0.5 ${m.direction === 'up' ? 'text-green-400' : 'text-amber-400'}`}>{m.delta}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ADR 0025's fixed reason taxonomy -- expected to need revisiting once real
// denials start happening, per that ADR's own "Consequences" section.
const DENY_REASONS = [
  'Design/requirements mismatch',
  'Insufficient tests',
  'Evidence missing',
  'Regression/quality'
]

function DenyModal({ pr, onClose, onDenied }) {
  const [selected, setSelected] = useState([])
  const [comment, setComment] = useState('')
  const [status, setStatus] = useState('idle') // idle | sending | error
  const [errorMessage, setErrorMessage] = useState(null)

  function toggleReason(reason) {
    setSelected((prev) => (prev.includes(reason) ? prev.filter((r) => r !== reason) : [...prev, reason]))
  }

  async function handleAction(action) {
    setStatus('sending')
    setErrorMessage(null)
    try {
      const result = await window.api.mr.deny({
        number: pr.number,
        url: pr.url,
        ticketNumber: pr.ticketNumber,
        action,
        reasons: selected,
        comment
      })
      if (result.cancelled) {
        // Another window/tab is already merging this PR: show that, don't reset the button.
        setStatus(result.alreadyMerging ? 'approving' : 'idle')
        return
      }
      onDenied(pr.number)
    } catch (err) {
      setStatus('error')
      setErrorMessage(String(err))
    }
  }

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md rounded-lg border border-neutral-800 bg-neutral-900 p-5">
        <h3 className="mb-1 font-mono text-sm font-semibold text-white">
          Deny #{pr.number} — {pr.title}
        </h3>
        <p className="mb-3 text-xs text-neutral-500">
          Send feedback tags the ticket for a future re-engagement pass. Drop entirely closes the PR and ticket
          with no re-engagement expected.
        </p>
        <div className="mb-3 flex flex-col gap-1.5">
          {DENY_REASONS.map((reason) => (
            <label key={reason} className="flex items-center gap-2 text-sm text-neutral-300">
              <input type="checkbox" checked={selected.includes(reason)} onChange={() => toggleReason(reason)} />
              {reason}
            </label>
          ))}
        </div>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Optional free-text comment"
          rows={3}
          className="mb-3 w-full rounded-md border border-neutral-800 bg-neutral-950 p-2 text-sm text-neutral-200 placeholder:text-neutral-600"
        />
        {status === 'error' && <p className="mb-2 text-sm text-red-400">Failed: {errorMessage}</p>}
        <div className="flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            disabled={status === 'sending'}
            className="rounded-md px-3 py-1.5 text-sm text-neutral-400 transition-colors hover:text-neutral-200 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => handleAction('drop')}
            disabled={status === 'sending'}
            className="rounded-md bg-red-950 px-3 py-1.5 text-sm font-medium text-red-300 transition-colors hover:bg-red-900 disabled:opacity-50"
          >
            Drop Entirely
          </button>
          <button
            onClick={() => handleAction('send_feedback')}
            disabled={status === 'sending'}
            className="rounded-md bg-amber-700 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-amber-600 disabled:opacity-50"
          >
            {status === 'sending' ? 'Sending…' : 'Send Feedback'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Shared by PrCard (the list row) and MrDetail (the deep-dive page) so
// approve/deny behave and look identical in both places, per Gil's
// request -- one implementation, not a second copy that could drift.
const REWORK_TONE = {
  running: 'border-blue-800 text-blue-300',
  queued: 'border-amber-800 text-amber-300',
  paused: 'border-red-800 text-red-300',
  'needs-person': 'border-red-800 text-red-300',
  held: 'border-neutral-700 text-neutral-300',
  blocked: 'border-amber-800 text-amber-300',
  'not-queued': 'border-red-800 text-red-300'
}

export function ApproveDenyActions({ pr, onApproved, onDenied }) {
  const [status, setStatus] = useState('idle') // idle | approving | error | reengaged
  const [errorMessage, setErrorMessage] = useState(null)
  const [showDenyModal, setShowDenyModal] = useState(false)
  const [clearing, setClearing] = useState(null) // null | 'confirm' | 'working' | 'done' | { failed }

  // The merge runs in the main process, so this button can be unmounted (you navigate away) and
  // remounted mid-merge. Ask the main process what this PR is doing, and keep asking while it merges.
  useEffect(() => {
    let cancelled = false
    let timer
    const check = async () => {
      try {
        const m = await window.api.mr.mergeState(pr.url)
        if (cancelled) return
        if (m.state === 'merging') {
          setStatus('approving')
          timer = setTimeout(check, 2000)
        } else if (m.state === 'reengaged' || m.state === 'error') {
          setStatus(m.state)
          setErrorMessage(m.reason)
        } else {
          setStatus((s) => (s === 'approving' ? 'idle' : s))
        }
      } catch { /* keep whatever this component already knows */ }
    }
    check()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [pr.url])

  async function handleApprove() {
    setStatus('approving')
    setErrorMessage(null)
    try {
      const result = await window.api.mr.approve({ number: pr.number, url: pr.url })
      if (result.cancelled) {
        setStatus('idle')
        return
      }
      // G-Eskayo/marvin#91's merge-time gate: a rebase or retest failure
      // blocks the merge and routes to re-engagement instead -- a real
      // outcome the user needs to see, not the same thing as onApproved's
      // "it merged" path, and not a tooling failure either.
      if (result.reengaged) {
        setStatus('reengaged')
        setErrorMessage(result.reason)
        return
      }
      onApproved(pr.number)
    } catch (err) {
      setStatus('error')
      setErrorMessage(cleanIpcError(err))
    }
  }

  if (pr.canMerge === false) {
    // The merge gate runs marvin's own tests, so other projects' PRs are reviewed on GitHub.
    return (
      <div className="flex shrink-0 flex-col items-end gap-1 text-right">
        <a href={pr.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="rounded-md border border-neutral-700 px-4 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800">
          Review on GitHub ↗
        </a>
        <p className="max-w-[16rem] text-xs text-neutral-600">Merging {pr.repo.split('/')[1]} from here isn't set up: its project profile hasn't opted in (merge_from_dashboard).</p>
      </div>
    )
  }

  const view = describePrState(pr, { status, errorMessage })
  const TONE = { ready: 'text-emerald-400', wait: 'text-amber-400', blocked: 'text-red-400', working: 'text-blue-400' }

  async function clearSentBack() {
    setClearing('working')
    try {
      const r = await window.api.mr.clearSentBack(pr.url)
      if (r.cleared) { setClearing('done'); onApproved?.(null) } // refresh the list: the PR is no longer sent back
      else { setClearing({ failed: r.reason }) }
    } catch (err) {
      setClearing({ failed: cleanIpcError(err) })
    }
  }

  return (
    <div className="flex shrink-0 flex-col items-end gap-1" data-state={view.kind}>
      {view.approve !== 'hidden' || view.deny !== 'hidden' ? (
        <div className="flex gap-2">
          {view.deny !== 'hidden' && (
            <button
              onClick={() => setShowDenyModal(true)}
              disabled={view.deny === 'disabled'}
              className="rounded-md border border-neutral-700 px-4 py-1.5 text-sm font-medium text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
            >
              Deny
            </button>
          )}
          {view.approve !== 'hidden' && (
            <button
              onClick={handleApprove}
              disabled={view.approve === 'disabled'}
              className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
            >
              Approve &amp; Merge
            </button>
          )}
        </div>
      ) : null}
      <p className={`max-w-xs text-right text-sm font-medium ${TONE[view.tone] || ''}`}>{view.headline}</p>
      {view.detail && <p className="max-w-xs text-right text-xs text-neutral-400">{view.detail}</p>}
      {view.note && <p className="text-right text-xs text-emerald-400">{view.note}</p>}
      {view.rework && (
        <div className={`max-w-xs rounded-md border px-2 py-1 text-right text-xs ${REWORK_TONE[view.rework.state] || 'border-neutral-700 text-neutral-300'}`} data-rework={view.rework.state}>
          <p className="font-medium">{view.rework.headline}</p>
          <p className="mt-0.5 opacity-80">{view.rework.detail}</p>
        </div>
      )}
      {view.actions.map((a) =>
        a.id === 'clearSentBack' ? (
          <div key={a.id} className="max-w-xs text-right text-xs">
            {clearing === 'confirm' ? (
              <span className="text-neutral-300">
                Clear it?{' '}
                <button onClick={clearSentBack} className="text-sky-400 hover:underline">Yes, clear</button>
                {' · '}
                <button onClick={() => setClearing(null)} className="text-neutral-500 hover:underline">Cancel</button>
              </span>
            ) : clearing === 'working' ? (
              <span className="text-neutral-500">Clearing…</span>
            ) : (
              <button onClick={() => setClearing('confirm')} className="text-sky-400 hover:underline">{a.label}</button>
            )}
            {clearing && clearing.failed && <p className="mt-1 text-amber-400">{clearing.failed}</p>}
          </div>
        ) : null
      )}
      {showDenyModal && (
        <DenyModal
          pr={pr}
          onClose={() => setShowDenyModal(false)}
          onDenied={(number) => {
            setShowDenyModal(false)
            onDenied(number)
          }}
        />
      )}
    </div>
  )
}

const PARITY_STYLE = {
  ok: 'bg-emerald-950 text-emerald-300',
  'sent-back': 'bg-amber-950 text-amber-300',
  'no-ticket': 'bg-red-950 text-red-300',
  elsewhere: 'bg-red-950 text-red-300'
}
const COLUMN_NAME = { backlog: 'Backlog', ready: 'Ready', blocked: 'Blocked', progress: 'In progress', review: 'In review', done: 'Done' }

// The PR's ticket and where it sits on the project's board: the one-to-one between this list and the boards.
function TicketLine({ row, onOpenTicket }) {
  if (!row) return null
  const t = row.ticket
  return (
    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs">
      {t ? (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onOpenTicket?.(t.repo, t.number)
          }}
          className="truncate text-left text-neutral-400 hover:text-white"
          title="Open this ticket on its board"
        >
          closes <span className="font-mono text-neutral-500">#{t.number}</span> {t.title} →
        </button>
      ) : (
        <span className="text-neutral-500">closes no ticket</span>
      )}
      <span className={`rounded px-1.5 py-0.5 text-[10px] ${PARITY_STYLE[row.status]}`}>
        {row.status === 'ok' && 'board: In review ✓'}
        {row.status === 'sent-back' && 'sent back: waiting for rework'}
        {row.status === 'no-ticket' && 'no card on any board'}
        {row.status === 'elsewhere' && `board: ${COLUMN_NAME[t.column]} ✗`}
      </span>
    </p>
  )
}

function ParitySummary({ parity }) {
  if (!parity) return null
  const n = parity.prs.length
  return (
    <div className={`rounded border px-3 py-2 text-xs ${parity.ok ? 'border-emerald-900 bg-emerald-950/40 text-emerald-300' : 'border-red-900 bg-red-950/40 text-red-300'}`}>
      {parity.ok ? (
        <>Matches the boards: each of the {n} open PR{n === 1 ? '' : 's'} is paired with its ticket, and every ticket under “In review” has a PR here.</>
      ) : (
        <>
          <p className="font-medium">The boards and this list disagree:</p>
          <ul className="mt-1 list-disc pl-5">
            {parity.problems.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function PrCard({ pr, parity, onOpenTicket, onApproved, onDenied, onSelect }) {
  return (
    <div
      onClick={() => onSelect(pr)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelect(pr)
      }}
      className="cursor-pointer rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition-colors hover:border-neutral-700 hover:bg-neutral-800/50"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <p className="font-mono text-sm font-semibold text-white">
            #{pr.number} — {pr.title}{' '}
            {pr.repo !== 'G-Eskayo/marvin' && <span className="rounded bg-sky-950 px-1.5 py-0.5 font-sans text-[10px] font-normal text-sky-300">{pr.repo.split('/')[1]}</span>}
          </p>
          {pr.hasSchema ? (
            pr.evidence.subsystem && (
              <p className="text-xs text-neutral-500">
                {pr.evidence.subsystem} <VerdictBadge verdict={pr.evidence.verdict} />
              </p>
            )
          ) : (
            <p className="text-xs text-amber-400">No structured evidence — needs a manual look</p>
          )}
          <TicketLine row={parity} onOpenTicket={onOpenTicket} />
        </div>
        {/* Approve/Deny live inside the same clickable card -- stop the
            click from also bubbling up to onSelect and opening the detail
            view underneath whatever action was just taken. Works
            identically for a non-schema PR -- the webhook only ever
            needed the PR url, never the parsed evidence. */}
        <div onClick={(e) => e.stopPropagation()}>
          <ApproveDenyActions pr={pr} onApproved={onApproved} onDenied={onDenied} />
        </div>
      </div>
      {pr.hasSchema ? (
        <EvidenceTable metrics={pr.evidence.metrics} />
      ) : (
        <p className="whitespace-pre-wrap font-mono text-xs text-neutral-500">
          {pr.rawBody.slice(0, 400)}
          {pr.rawBody.length > 400 ? '…' : ''}
        </p>
      )}
      {pr.ticketRef && Object.keys(pr.stages).length > 0 && <StageStrip stages={pr.stages} rebase={pr.rebase} isLiveNow={pr.isLiveNow} now={Date.now()} onStageClick={() => onSelect(pr)} />}
    </div>
  )
}

export default function MrReview({ nav, onOpenDocs, onOpenBoard, onOpenTicket }) {
  const [prs, setPrs] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [parity, setParity] = useState(null)

  function reload() {
    window.api.mr.parity().then(setParity).catch(() => setParity(null))
    window.api.mr
      .list()
      .then((list) => {
        setPrs(list)
        // Opening this list is what "seen" means for the tab's status dot
        // (App.jsx) -- mark every currently-listed PR, not just ones you
        // click into, since the dot is about "have you looked at the
        // list," not "have you opened every item on it."
        window.api.mr.markSeen(list.map((pr) => pr.key)).catch(() => {})
      })
      .catch((err) => setError(String(err)))
  }

  // Previously fetch-once-on-mount only -- a new MR raised while this tab
  // was already open never appeared until you switched away and back
  // (which remounts the component). Now refreshes on window.api.mr.onRefresh
  // (pushed the moment a PR is raised, see refresh_server.js), with a long
  // poll as a pure safety net for whatever that push misses. Harmless to
  // keep running while a detail view is open since `selected` doesn't
  // depend on `prs`.
  useEffect(() => {
    reload()
    const interval = setInterval(reload, MR_LIST_REFRESH_MS)
    const unsubscribe = window.api.mr.onRefresh(reload)
    return () => {
      clearInterval(interval)
      unsubscribe()
    }
  }, [])

  // Deep link from an Activity board card: open that PR's detail once the list has it.
  const handledNav = useRef(null)
  useEffect(() => {
    if (!nav?.prKey || !prs || handledNav.current === nav.at) return
    const target = prs.find((p) => p.key === nav.prKey)
    if (target) setSelected(target)
    handledNav.current = nav.at
  }, [nav?.at, prs])

  // A denied/approved PR stops being an open PR, so its detail view no
  // longer has anything to show -- same reasoning as returning to the list
  // rather than a broken drill-down.
  function reloadAndReturnToList() {
    setSelected(null)
    reload()
  }

  if (selected) {
    return (
      <MrDetail
        pr={selected}
        onOpenDocs={onOpenDocs}
        onOpenBoard={onOpenBoard}
        onOpenTicket={onOpenTicket}
        onBack={() => setSelected(null)}
        onApproved={reloadAndReturnToList}
        onDenied={reloadAndReturnToList}
      />
    )
  }

  if (error) {
    return <div className="flex h-full items-center justify-center text-red-400">Failed to load MRs: {error}</div>
  }
  if (prs === null) {
    return <div className="flex h-full items-center justify-center text-neutral-500">Loading…</div>
  }
  if (prs.length === 0) {
    return <EmptyState />
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <p className="text-sm text-neutral-500">
        {prs.length} pipeline-raised PR{prs.length === 1 ? '' : 's'} awaiting review. Click a title for the full
        detail view.
      </p>
      <ParitySummary parity={parity} />
      {prs.map((pr) => (
        <PrCard
          key={pr.key}
          pr={pr}
          parity={parity?.prs.find((r) => r.key === pr.key)}
          onOpenTicket={onOpenTicket}
          onApproved={reloadAndReturnToList}
          onDenied={reloadAndReturnToList}
          onSelect={setSelected}
        />
      ))}
    </div>
  )
}
