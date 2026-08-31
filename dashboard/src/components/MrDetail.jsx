import { useEffect, useState } from 'react'
import { EvidenceTable, ApproveDenyActions } from './MrReview.jsx'

// Full evidence-schema drill-down for one MR (G-Eskayo/marvin#72, ADR
// 0024) plus its linked ticket/parent-PRD requirements, design, and
// tasks -- fetched live via window.api.mr.ticketContext rather than
// duplicated into the PR body itself. Navigation matches
// SubsystemDrilldown's pattern (a dedicated view within the tab, back
// button, not a modal or inline row expand) -- MrReview.jsx swaps this in
// for the list the same way MetricsScorecard.jsx swaps in
// SubsystemDrilldown.

function Section({ title, children }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h4 className="mb-2 font-mono text-sm font-semibold text-white">{title}</h4>
      {children}
    </div>
  )
}

function TestResultsSection({ testResults }) {
  if (!testResults || testResults.total === null) {
    return <p className="text-sm text-neutral-500">Not available.</p>
  }
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-xs text-neutral-500">Suite</dt>
        <dd className="truncate font-mono text-neutral-200">{testResults.suite}</dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-500">Passed</dt>
        <dd className="font-mono text-green-400">{testResults.passed}</dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-500">Failed</dt>
        <dd className={`font-mono ${testResults.failed > 0 ? 'text-red-400' : 'text-neutral-200'}`}>
          {testResults.failed}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-neutral-500">Total</dt>
        <dd className="font-mono text-neutral-200">{testResults.total}</dd>
      </div>
    </dl>
  )
}

function DevEvidenceSection({ devEvidence }) {
  if (!devEvidence) {
    return <p className="text-sm text-neutral-500">Not available.</p>
  }
  if (devEvidence.na) {
    return <p className="text-sm text-neutral-500">N/A — {devEvidence.reason || 'no UI'}</p>
  }
  return (
    <div className="text-sm">
      {devEvidence.screenshot && (
        <p className="mb-1 font-mono text-xs text-neutral-400">Screenshot: {devEvidence.screenshot}</p>
      )}
      {devEvidence.description && <p className="text-neutral-300">{devEvidence.description}</p>}
    </div>
  )
}

// Renders an issue's raw body as preformatted text rather than pulling in
// a markdown-rendering dependency for one drill-down section -- structure
// (headers, lists) stays legible even unrendered, and this ticket's own
// acceptance criteria only asks that requirements/design/tasks show up,
// not that they render as styled markdown.
function IssueBody({ label, issue }) {
  if (!issue) {
    return <p className="text-sm text-neutral-500">Not available.</p>
  }
  return (
    <div>
      <p className="mb-2 text-sm font-medium text-neutral-300">
        {label} #{issue.number} — {issue.title}
      </p>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-neutral-950 p-3 text-xs text-neutral-300">
        {issue.body}
      </pre>
    </div>
  )
}

export default function MrDetail({ pr, onBack, onApproved, onDenied }) {
  const [context, setContext] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    if (!pr.ticketNumber) {
      setContext({ ticket: null, parent: null })
      return
    }
    window.api.mr
      .ticketContext(pr.ticketNumber)
      .then((result) => {
        if (!cancelled) setContext(result)
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    return () => {
      cancelled = true
    }
  }, [pr.ticketNumber])

  const contextLoading = context === null && !error

  return (
    <div className="flex flex-col gap-4 p-6">
      <button onClick={onBack} className="text-sm text-neutral-400 hover:text-neutral-200">
        ← Back to MR Review
      </button>

      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-mono text-lg font-semibold text-white">
            #{pr.number} — {pr.title}
          </h2>
          {pr.evidence.subsystem && (
            <p className="text-sm text-neutral-500">
              {pr.evidence.subsystem} — {pr.evidence.verdict}
            </p>
          )}
          <a href={pr.url} target="_blank" rel="noreferrer" className="text-xs text-blue-400 hover:underline">
            {pr.url}
          </a>
        </div>
        <ApproveDenyActions pr={pr} onApproved={onApproved} onDenied={onDenied} />
      </div>

      <Section title="Metrics Comparison">
        <EvidenceTable metrics={pr.evidence.metrics} />
      </Section>

      <Section title="Test Results">
        <TestResultsSection testResults={pr.evidence.testResults} />
      </Section>

      <Section title="Dev Environment Evidence">
        <DevEvidenceSection devEvidence={pr.evidence.devEvidence} />
      </Section>

      <Section title="Requirements & Tasks (linked ticket)">
        {contextLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : error ? (
          <p className="text-sm text-red-400">Failed to load: {error}</p>
        ) : (
          <IssueBody label="Ticket" issue={context.ticket} />
        )}
      </Section>

      <Section title="Design & Architecture (parent PRD)">
        {contextLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : error ? (
          <p className="text-sm text-red-400">Failed to load: {error}</p>
        ) : (
          <IssueBody label="Parent" issue={context.parent} />
        )}
      </Section>
    </div>
  )
}
