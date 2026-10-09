import { useEffect, useState } from 'react'
import { EvidenceTable, ApproveDenyActions } from './MrReview.jsx'
import { projectIdOf } from '../lib/projects.js'
import Related, { useRelated } from './Related.jsx'
import PrImages from './PrImages.jsx'
import Decisions from './Decisions.jsx'

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

// The evidence screenshot, matched to its resolved entry in the PR's images (a repo-relative path resolves to the PR branch).
export function evidenceImage(screenshot, images) {
  if (!screenshot) return null
  const tail = String(screenshot).replace(/^\.?\//, '')
  return (images || []).find((img) => img.url === screenshot || img.url.endsWith(`/${tail}`)) || null
}

function DevEvidenceSection({ devEvidence, images }) {
  if (!devEvidence) {
    return <p className="text-sm text-neutral-500">Not available.</p>
  }
  if (devEvidence.na) {
    return <p className="text-sm text-neutral-500">N/A — {devEvidence.reason || 'no UI'}</p>
  }
  const shot = evidenceImage(devEvidence.screenshot, images)
  return (
    <div className="text-sm">
      {shot ? (
        <PrImages images={[{ ...shot, group: null }]} />
      ) : devEvidence.screenshot && (
        <p className="mb-1 font-mono text-xs text-neutral-400">Screenshot: {devEvidence.screenshot}</p>
      )}
      {devEvidence.description && <p className="mt-2 text-neutral-300">{devEvidence.description}</p>}
    </div>
  )
}

// A UI change with no image in its description can't be approved (marvin #374); say so where the images would be.
function NeedsImages({ needsImages }) {
  return (
    <div className="rounded-lg border border-amber-700 bg-amber-950/40 p-4 text-sm text-amber-200">
      <p className="font-semibold">Needs images</p>
      <p className="mt-1 text-amber-300/90">This PR changes how something looks but its description has no screenshots or mock-ups, so it can't be approved yet.</p>
      {needsImages.files?.length > 0 && (
        <p className="mt-2 font-mono text-xs text-amber-400/80">{needsImages.files.slice(0, 8).join(', ')}{needsImages.files.length > 8 ? ` +${needsImages.files.length - 8} more` : ''}</p>
      )}
    </div>
  )
}

function DeviceSection({ device }) {
  if (!device) {
    return <p className="text-sm text-neutral-500">Not available.</p>
  }
  return <p className="font-mono text-sm text-neutral-200">{device}</p>
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

export default function MrDetail({ pr, onBack, onApproved, onDenied, onOpenDocs, onOpenBoard, onOpenTicket, onChanged }) {
  const rel = useRelated(() => window.api.relations.pr(pr.repo, pr.number), [pr.repo, pr.number])
  const [context, setContext] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    if (!pr.ticketNumber) {
      setContext({ ticket: null, parent: null })
      return
    }
    window.api.mr
      .ticketContext(pr.ticketNumber, pr.repo)
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
          {pr.hasSchema && pr.evidence.subsystem && (
            <p className="text-sm text-neutral-500">
              {pr.evidence.subsystem} — {pr.evidence.verdict}
            </p>
          )}
          {!pr.hasSchema && <p className="text-sm text-amber-400">No structured evidence — needs a manual look</p>}
          <a href={pr.url} target="_blank" rel="noreferrer" className="text-xs text-blue-400 hover:underline">
            {pr.url}
          </a>
          <p className="mt-1 text-xs text-neutral-500">
            Project: <span className="text-neutral-300">{pr.repo.split('/')[1]}</span>
            {onOpenDocs && (
              <button onClick={() => onOpenDocs(projectIdOf(pr.repo))} className="ml-2 text-neutral-400 hover:text-white">
                Docs →
              </button>
            )}
            {onOpenBoard && (
              <button onClick={() => onOpenBoard(pr.repo)} className="ml-2 text-neutral-400 hover:text-white">
                Board →
              </button>
            )}
          </p>
        </div>
        <ApproveDenyActions pr={pr} onApproved={onApproved} onDenied={onDenied} />
      </div>

      {/* What the PR asks the owner to choose: answered here, and Approve waits until the required ones are. */}
      {pr.decisions?.present && (
        <Decisions
          key={JSON.stringify(pr.decisions.questions)}
          repo={pr.repo}
          number={pr.number}
          decisions={pr.decisions}
          onSubmitted={() => onChanged?.()}
        />
      )}

      {pr.images?.length > 0 && (
        <Section title={`Images & recordings (${pr.images.length})`}>
          <PrImages images={pr.images} />
        </Section>
      )}
      {!pr.images?.length && pr.needsImages && <NeedsImages needsImages={pr.needsImages} />}

      {pr.hasSchema ? (
        <>
          <Section title="Device">
            <DeviceSection device={pr.evidence.device} />
          </Section>

          <Section title="Metrics Comparison">
            <EvidenceTable metrics={pr.evidence.metrics} />
          </Section>

          <Section title="Test Results">
            <TestResultsSection testResults={pr.evidence.testResults} />
          </Section>

          <Section title="Dev Environment Evidence">
            <DevEvidenceSection devEvidence={pr.evidence.devEvidence} images={pr.images} />
          </Section>
        </>
      ) : (
        <Section title="PR Description (no structured evidence template)">
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-neutral-950 p-3 text-xs text-neutral-300">
            {pr.rawBody}
          </pre>
        </Section>
      )}

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

      <Related
        rel={rel}
        onDoc={(project, path) => onOpenDocs?.(project, path)}
        onTicket={(repo, number) => onOpenTicket?.(repo, number)}
      />
    </div>
  )
}
