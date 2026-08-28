import { useEffect, useState } from 'react'
import MrDetail from './MrDetail.jsx'

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-neutral-500">
      <p className="text-lg font-medium text-neutral-300">No MRs waiting on you</p>
      <p className="max-w-md text-sm">
        This fills in once the pipeline's sandbox orchestration raises a PR with metrics evidence attached.
        Manually-opened PRs (like this dashboard's own) don't show up here on purpose.
      </p>
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
        setStatus('idle')
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

function PrCard({ pr, onApproved, onDenied, onSelect }) {
  const [status, setStatus] = useState('idle') // idle | approving | error
  const [errorMessage, setErrorMessage] = useState(null)
  const [showDenyModal, setShowDenyModal] = useState(false)

  async function handleApprove() {
    setStatus('approving')
    setErrorMessage(null)
    try {
      const result = await window.api.mr.approve({ number: pr.number, url: pr.url })
      if (result.cancelled) {
        setStatus('idle')
        return
      }
      onApproved(pr.number)
    } catch (err) {
      setStatus('error')
      setErrorMessage(String(err))
    }
  }

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <button
            onClick={() => onSelect(pr)}
            className="text-left font-mono text-sm font-semibold text-white hover:underline"
          >
            #{pr.number} — {pr.title}
          </button>
          {pr.evidence.subsystem && (
            <p className="text-xs text-neutral-500">
              {pr.evidence.subsystem} <VerdictBadge verdict={pr.evidence.verdict} />
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            onClick={() => setShowDenyModal(true)}
            disabled={status === 'approving'}
            className="rounded-md border border-neutral-700 px-4 py-1.5 text-sm font-medium text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
          >
            Deny
          </button>
          <button
            onClick={handleApprove}
            disabled={status === 'approving'}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
          >
            {status === 'approving' ? 'Confirming…' : 'Approve & Merge'}
          </button>
        </div>
      </div>
      <EvidenceTable metrics={pr.evidence.metrics} />
      {status === 'error' && <p className="mt-2 text-sm text-red-400">Failed: {errorMessage}</p>}
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

export default function MrReview() {
  const [prs, setPrs] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)

  function reload() {
    window.api.mr
      .list()
      .then(setPrs)
      .catch((err) => setError(String(err)))
  }

  useEffect(reload, [])

  // A denied/approved PR stops being an open PR, so its detail view no
  // longer has anything to show -- same reasoning as returning to the list
  // rather than a broken drill-down.
  function reloadAndReturnToList() {
    setSelected(null)
    reload()
  }

  if (selected) {
    return <MrDetail pr={selected} onBack={() => setSelected(null)} />
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
      {prs.map((pr) => (
        <PrCard
          key={pr.number}
          pr={pr}
          onApproved={reloadAndReturnToList}
          onDenied={reloadAndReturnToList}
          onSelect={setSelected}
        />
      ))}
    </div>
  )
}
