import { useEffect, useState } from 'react'
import { EvidenceTable, ApproveDenyActions, CorrectionNotice } from './MrReview.jsx'
import { projectIdOf } from '../lib/projects.js'
import StageStrip from './StageStrip.jsx'
import Related, { useRelated } from './Related.jsx'
import PrImages, { showImage } from './PrImages.jsx'
import MockupLauncher from './MockupLauncher.jsx'
import { imageRefsFor } from '../lib/decision_refs.js'
import Decisions from './Decisions.jsx'
import IssueBodyView from './IssueBody.jsx'

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

// A linked ticket or parent PRD, rendered for reading (owner, 2026-10-09: "format descriptions in tickets instead of just
// having them as scrollable text boxes"); see IssueBody.jsx.
function IssueBody({ label, issue, repo, onOpenTicket, onOpenDocs }) {
  if (!issue) {
    return <p className="text-sm text-neutral-500">Not available.</p>
  }
  return (
    <div>
      <p className="mb-3 text-sm font-medium text-neutral-300">
        {label} #{issue.number}: {issue.title}
      </p>
      <IssueBodyView
        body={issue.body}
        updatedAt={issue.updatedAt}
        ctx={repo ? { repo } : null}
        onLink={(l) => (l.type === 'ticket' ? onOpenTicket?.(l.repo, l.number) : onOpenDocs?.(l.project, l.path))}
      />
    </div>
  )
}

// A long summary opens clamped, so the mock-up and the first pictures still show in the first screen at 1200 px.
export const SUMMARY_CLAMP_CHARS = 420
function SummarySection({ summary, repo, headRef, onOpenTicket, onOpenDocs }) {
  const long = summary.length > SUMMARY_CLAMP_CHARS
  const [open, setOpen] = useState(!long)
  return (
    <Section title="What it is">
      <div data-summary="1" data-clamped={open ? undefined : '1'} className={open ? '' : 'relative max-h-[9.5rem] overflow-hidden'}>
        <IssueBodyView
          body={summary}
          ctx={{ repo }}
          headRef={headRef}
          onLink={(l) => (l.type === 'ticket' ? onOpenTicket?.(l.repo, l.number) : onOpenDocs?.(l.project, l.path))}
        />
        {!open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-neutral-900 to-transparent" />}
      </div>
      {long && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="mt-1 text-xs text-sky-400 hover:text-sky-300 hover:underline">
          {open ? 'Show less' : 'Read the rest'}
        </button>
      )}
    </Section>
  )
}

// Where "Jump to the Decisions" lands.
const DECISIONS_ANCHOR = 'mr-decisions'
// The main gallery's anchors (Decisions link to them) and how many images show before "Show all".
const GALLERY = 'pr-image'
export const GALLERY_LIMIT = 6

export default function MrDetail({ pr, onBack, onApproved, onDenied, onOpenDocs, onOpenBoard, onOpenTicket, onChanged, notice = null }) {
  const rel = useRelated(() => window.api.relations.pr(pr.repo, pr.number), [pr.repo, pr.number])
  const [context, setContext] = useState(null)
  const [error, setError] = useState(null)
  const [prEvents, setPrEvents] = useState([])

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

  useEffect(() => {
    if (pr.ticketNumber) {
      window.api.activity.timeline(pr.ticketNumber, pr.repo).then(setPrEvents).catch(() => {})
    }
  }, [pr.ticketNumber, pr.repo])

  const contextLoading = context === null && !error

  return (
    <div className="flex flex-col gap-4 p-6">
      <button onClick={onBack} className="text-sm text-neutral-400 hover:text-neutral-200">
        ← Back to {pr.readOnly ? 'merged history' : 'MR Review'}
      </button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-80">
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
            {/* The screenshots come first, so the Decisions can be far down (owner's answer on PR #953). */}
            {pr.decisions?.present && !pr.readOnly && (
              <button data-jump-decisions="1" onClick={() => document.getElementById(DECISIONS_ANCHOR)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                className="ml-2 text-sky-400 hover:text-sky-300">
                Jump to the Decisions ↓
              </button>
            )}
          </p>
        </div>
        {pr.readOnly ? (
          <span data-readonly="1" className={`rounded px-2 py-1 text-xs ${pr.state === 'MERGED' ? 'bg-emerald-900/50 text-emerald-300' : 'bg-neutral-800 text-neutral-300'}`}>
            {pr.state === 'MERGED' ? `Merged${pr.mergedAt ? ` ${new Date(pr.mergedAt).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : ''}` : (pr.state || 'Read-only').toLowerCase()} · read-only
          </span>
        ) : (
          <ApproveDenyActions pr={pr} onApproved={onApproved} onDenied={onDenied} inDetail />
        )}
      </div>

      {notice && <CorrectionNotice notice={notice} />}

      {pr.refusal && (
        <div data-refusal="1" className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Approve refused {new Date(pr.refusal.at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}: <strong>{pr.refusal.reason}</strong>
          {pr.refusal.message && <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-red-300/80">{pr.refusal.message}</p>}
        </div>
      )}

      {/* What to look at comes before the choices (#938): what it is, the mock-up and the pictures, then the Decisions.
          You can't answer choices you can't see. */}
      {pr.summary && (
        <SummarySection summary={pr.summary} repo={pr.repo} headRef={pr.headRef} onOpenTicket={onOpenTicket} onOpenDocs={onOpenDocs} />
      )}

      <MockupLauncher pr={pr} />

      {pr.images?.length > 0 && (
        <Section title={`Images & recordings (${pr.images.length})`}>
          <PrImages images={pr.images} size="large" anchorPrefix={GALLERY} limit={GALLERY_LIMIT} />
        </Section>
      )}
      {!pr.images?.length && pr.needsImages && <NeedsImages needsImages={pr.needsImages} />}

      {/* What the PR asks the owner to choose: answered here, and Approve waits until the required ones are. */}
      {pr.decisions?.present && !pr.readOnly && (
        <div id={DECISIONS_ANCHOR} className="scroll-mt-4">
        <Decisions
          key={JSON.stringify(pr.decisions.questions.map((q) => [q.id, q.question, q.options.map((o) => o.label)]))}
          repo={pr.repo}
          number={pr.number}
          decisions={pr.decisions}
          refsFor={(q) => imageRefsFor(q.question, pr.images)}
          onSeeImage={(index) => showImage(GALLERY, index)}
          onSubmitted={(r) => onChanged?.(r)}
        />
        </div>
      )}

      {prEvents.length > 0 && (
        <Section title="Pipeline">
          <StageStrip events={prEvents} />
        </Section>
      )}

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
          <IssueBodyView
            body={pr.rawBody}
            ctx={{ repo: pr.repo }}
            headRef={pr.headRef}
            onLink={(l) => (l.type === 'ticket' ? onOpenTicket?.(l.repo, l.number) : onOpenDocs?.(l.project, l.path))}
          />
        </Section>
      )}

      <Section title="Requirements & Tasks (linked ticket)">
        {contextLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : error ? (
          <p className="text-sm text-red-400">Failed to load: {error}</p>
        ) : (
          <IssueBody label="Ticket" issue={context.ticket} repo={pr.repo} onOpenTicket={onOpenTicket} onOpenDocs={onOpenDocs} />
        )}
      </Section>

      <Section title="Design & Architecture (parent PRD)">
        {contextLoading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : error ? (
          <p className="text-sm text-red-400">Failed to load: {error}</p>
        ) : (
          <IssueBody label="Parent" issue={context.parent} repo={pr.repo} onOpenTicket={onOpenTicket} onOpenDocs={onOpenDocs} />
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
