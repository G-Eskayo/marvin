import { useEffect, useMemo, useState } from 'react'
import { ApproveDenyActions } from './MrReview.jsx'
import { SummarySection, PrEvidenceSections, NeedsImages, DECISIONS_ANCHOR, GALLERY, GALLERY_LIMIT } from './MrDetail.jsx'
import { HumanTaskPanel, TicketReply } from './ProjectBoard.jsx'
import Decisions from './Decisions.jsx'
import PrImages, { showImage } from './PrImages.jsx'
import MockupLauncher from './MockupLauncher.jsx'
import IssueBody from './IssueBody.jsx'
import Related, { useRelated } from './Related.jsx'
import { useScrollPlace } from './ScrollPlaces.jsx'
import { imageRefsFor } from '../lib/decision_refs.js'
import { summarizeDecisions } from '../../webhook-server/decisions.js'
import { parseHumanTask } from '../lib/human_task.js'
import { resolveItem, lifeStages, historyRows, barText, barWho, pinnedSha } from '../lib/workshop_item.js'
import { clock } from './WorkshopTab.jsx'

// The Workshop's item page (#863, ADR 0080): one page per unit of work, a ticket and its PRs, whichever you came from.
// It merges the board card's ticket drill-down and MR Review's PR detail, built to the approved mock-up (marvin-instance
// docs/screenshots/review-tab-item-860.png). Every control is the existing one, moved: Approve / Deny and the merge's
// progress are ApproveDenyActions, the answers are <Decisions>, the pictures PrImages, the reply TicketReply, the links
// Related. The page holds no rule of its own; whose move it is comes from next_step, as in the Now view.

const BAR_TONE = {
  yours: 'border-amber-700/70 bg-amber-950/40',
  marvin: 'border-sky-900/70 bg-sky-950/30',
  stuck: 'border-red-900/70 bg-red-950/40',
  waiting: 'border-neutral-800 bg-neutral-900/70',
  closed: 'border-neutral-800 bg-neutral-900/70'
}
const WHO_TONE = { yours: 'text-amber-400', marvin: 'text-sky-400', stuck: 'text-red-400', waiting: 'text-neutral-400', closed: 'text-neutral-400' }
const STRIP_NOW = { yours: 'bg-amber-500', marvin: 'bg-sky-400', stuck: 'bg-red-500', waiting: 'bg-neutral-500', closed: 'bg-neutral-500', done: 'bg-emerald-600' }
const LABEL_NOW = { yours: 'text-amber-400', marvin: 'text-sky-400', stuck: 'text-red-400', waiting: 'text-neutral-300', closed: 'text-neutral-300', done: 'text-emerald-400' }

function Card({ title, children, testid, aside = null }) {
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900/70 p-4" data-testid={testid}>
      {title && (
        <h3 className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 text-sm font-semibold text-neutral-400">
          <span className="min-w-0 break-words [overflow-wrap:anywhere]">{title}</span>
          {aside}
        </h3>
      )}
      {children}
    </section>
  )
}

export function LifeStrip({ stages }) {
  return (
    <ol className="grid grid-cols-7" aria-label="Life of this item" data-testid="life-strip">
      {stages.map((s) => (
        <li key={s.id} data-stage={s.id} data-state={s.state} aria-current={s.state === 'now' ? 'step' : undefined} className="min-w-0">
          <span className={`block h-[3px] ${s.state === 'done' ? 'bg-emerald-800' : s.state === 'now' ? STRIP_NOW[s.tone] : s.state === 'skipped' ? 'bg-neutral-700/60' : 'bg-neutral-800'}`} />
          <span className={`mt-2 block px-0.5 text-center text-[11px] leading-tight sm:text-xs ${s.state === 'now' ? `font-semibold ${LABEL_NOW[s.tone]}` : s.state === 'done' ? 'text-neutral-400' : 'text-neutral-600'}`}>
            {s.label}
          </span>
        </li>
      ))}
    </ol>
  )
}

export function ItemHistory({ rows, now }) {
  return (
    <Card title="History · the ticket’s stages" testid="item-history">
      {rows.length === 0 ? (
        <p className="text-sm text-neutral-500">No stages recorded yet.</p>
      ) : (
        <ul className="divide-y divide-neutral-800 border-t border-neutral-800">
          {rows.map((r, i) => (
            <li key={i} className="flex items-baseline justify-between gap-4 py-2 text-sm" data-status={r.status || undefined}>
              <span className={`min-w-0 break-words [overflow-wrap:anywhere] ${r.status === 'failed' ? 'text-red-400' : 'text-neutral-300'}`}>
                {r.text}
                {r.detail && <span className="mt-0.5 block whitespace-pre-wrap font-mono text-xs text-neutral-500">{r.detail}</span>}
              </span>
              <span className="shrink-0 tabular-nums text-neutral-400">{clock(r.at, now)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// The ticket's own text, comments and the reply box (TicketDrilldown's, moved). A long body opens folded.
function TicketCard({ repo, number, detail, error, stripDecisions, onLink, onSent }) {
  const [open, setOpen] = useState(false)
  const [showComments, setShowComments] = useState(false)
  if (error) return <Card title={`Ticket #${number}`} testid="item-ticket"><p className="text-sm text-red-400">Couldn’t read the ticket: {error}</p></Card>
  if (!detail) return <Card title={`Ticket #${number}`} testid="item-ticket"><p className="text-sm text-neutral-500">Loading…</p></Card>
  const labels = detail.labels?.map((l) => l.name || l) || []
  const long = (detail.body || '').length > 600
  const comments = detail.comments || []
  return (
    <Card title={`Ticket #${number}${detail.state === 'CLOSED' ? ' · closed' : ''}`} testid="item-ticket">
      <div className={long && !open ? 'relative max-h-[12rem] overflow-hidden' : ''}>
        <IssueBody body={detail.body} updatedAt={detail.updatedAt} ctx={{ repo }} stripDecisions={stripDecisions} onLink={onLink} />
        {long && !open && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-neutral-900 to-transparent" />}
      </div>
      {long && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="mt-1 text-xs text-sky-400 hover:text-sky-300 hover:underline">
          {open ? 'Show less' : 'Read the rest'}
        </button>
      )}
      {labels.includes('ready-for-human') && <HumanTaskPanel body={detail.body} ctx={{ repo }} />}
      {comments.length > 0 && (
        <div className="mt-3">
          <button type="button" onClick={() => setShowComments((s) => !s)} className="text-xs text-neutral-400 hover:text-neutral-200">
            {showComments ? '▾' : '▸'} {comments.length} comment{comments.length === 1 ? '' : 's'}
          </button>
          {showComments && comments.slice(-5).map((c, i) => (
            <div key={i} className="mt-3 border-l-2 border-neutral-800 pl-4">
              <p className="mb-1 text-xs text-neutral-500">{c.author?.login || c.author || ''}{c.createdAt ? ` · ${new Date(c.createdAt).toLocaleString()}` : ''}</p>
              <IssueBody body={c.body} ctx={{ repo }} compact stripDecisions={false} onLink={onLink} />
            </div>
          ))}
        </div>
      )}
      {detail.state !== 'CLOSED' && (
        <TicketReply repo={repo} number={number} labels={labels} state={detail.state} sendBack={parseHumanTask(detail.body).fields['What to send back']} onSent={onSent} />
      )}
    </Card>
  )
}

// Reads one thing for the page, again whenever `key` changes (the feed re-read on a trigger). Never on a timer.
function useRead(read, key, initial) {
  const [state, setState] = useState(() => (initial !== undefined ? { value: initial, error: null } : { value: null, error: null }))
  useEffect(() => {
    if (!read) return
    let live = true
    read().then((value) => live && setState({ value, error: null })).catch((e) => live && setState((s) => ({ value: s.value, error: String(e?.message || e) })))
    return () => { live = false }
  }, [key])
  return state
}

// target: { repo, pr?, ticket? } (workshop_item.itemTarget). feed: useWorkshopNow()'s value. `initial` seeds the reads
// (the tests render one frame with no IPC).
export default function WorkshopItem({ target, feed, onBack, onOpenItem, onOpenDocs, now = Date.now(), initial = {} }) {
  const api = globalThis.window?.api
  const value = feed?.value ? { ...feed.value, events: feed.events } : null
  const item = useMemo(() => (value ? resolveItem(target, value, now) : null), [feed?.value, feed?.events, target.repo, target.pr, target.ticket])
  const repo = target.repo
  const ticketNumber = item?.ticketNumber ?? target.ticket ?? null
  const refresh = feed?.at ?? 0

  const ticketRead = useRead(ticketNumber != null && api?.boards?.ticket ? () => api.boards.ticket(repo, ticketNumber) : null, `${repo}#${ticketNumber}|${refresh}`, initial.ticket)
  const closedRead = useRead(item?.closedPr != null && api?.mr?.historyDetail ? () => api.mr.historyDetail(`https://github.com/${repo}/pull/${item.closedPr}`) : null, `${repo}#${item?.closedPr}`, initial.closedPr)
  const eventsRead = useRead(ticketNumber != null && api?.activity?.timeline ? () => api.activity.timeline(ticketNumber, repo) : null, `${repo}#${ticketNumber}|${refresh}`, initial.events)
  const rel = useRelated(() => (initial.rel ? Promise.resolve(initial.rel) : target.pr != null ? api.relations.pr(repo, target.pr) : api.relations.ticket(repo, target.ticket)), [repo, target.pr, target.ticket])
  const [slot, setSlot] = useState(null)
  useScrollPlace('workshop-item', `${repo}|${target.pr ?? ''}|${target.ticket ?? ''}`)

  if (!item) {
    return (
      <div className="px-4 py-5 lg:px-6" data-testid="workshop-item">
        <BackLink onBack={onBack} />
        <p className="mt-6 text-sm text-neutral-500" data-testid="item-loading">{feed?.loaded ? 'Couldn’t read this item.' : 'Loading…'}</p>
      </div>
    )
  }

  const detail = ticketRead.value
  const closedPr = item.closedPr != null ? closedRead.value : null
  const pr = item.pr || closedPr || null
  const readOnly = !item.pr
  const step = item.step
  const who = item.step ? barWho(step) : barWho(null)
  const ticketHasDecisions = !!(detail?.body && summarizeDecisions(detail.body)?.present)
  const stages = lifeStages({ step, pr: readOnly ? null : pr, seen: pr, ticketDecisions: ticketHasDecisions, closedPrState: closedPr?.state || null, ticketState: detail?.state || null })
  const title = item.title || detail?.title || pr?.title || `#${target.pr ?? target.ticket}`
  const ticketDecisions = !pr && detail?.body ? summarizeDecisions(detail.body) : null
  const decisions = pr && !readOnly ? (pr.decisions?.present ? pr.decisions : null) : ticketDecisions?.present ? ticketDecisions : null
  const onLink = (l) => (l.type === 'ticket' ? onOpenItem?.({ repo: l.repo, ticket: l.number }) : onOpenDocs?.(l.project, l.path))
  const reload = () => feed?.reload?.()
  const pinned = pinnedSha(pr?.images)
  const rows = historyRows(eventsRead.value || [], { machines: feed?.value?.machines || {}, ticketCreatedAt: item.ticket?.createdAt || detail?.createdAt || null })

  return (
    <div className="flex max-w-[1100px] flex-col gap-4 px-4 py-5 lg:px-6" data-testid="workshop-item" data-item={`${repo}|${pr?.number ?? ''}|${ticketNumber ?? ''}`}>
      <BackLink onBack={onBack} />

      {/* The next-step bar: whose move, the one action, its buttons (next_step, ADR 0080 I4). */}
      <div className={`flex flex-wrap items-center justify-between gap-x-4 gap-y-3 rounded-lg border px-4 py-3 ${BAR_TONE[who.tone]}`} data-testid="next-step-bar" data-tone={who.tone}>
        <div className="min-w-0 flex-1 basis-56">
          <p className={`text-xs font-semibold uppercase tracking-[0.12em] ${WHO_TONE[who.tone]}`}>{step ? who.label : readOnly && pr?.state === 'MERGED' ? 'Merged' : 'Closed'}</p>
          <p className="mt-0.5 break-words text-base font-semibold text-neutral-100 [overflow-wrap:anywhere]">
            {step ? barText(step, pr) : pr?.mergedAt ? `Merged ${clock(Date.parse(pr.mergedAt), now)}` : 'Nothing left to do here'}
          </p>
        </div>
        {/* While Decisions wait, the bar's own words say it ("Answer 4 decisions, then approve"), so the card's repeat of
            it ("Answer the decisions first", the ids) is not shown here; Approve stays disabled by the same rule. */}
        <div className="flex min-w-0 flex-wrap items-start justify-end gap-2 [&_[data-state=decisions-pending]>p]:hidden [&>div]:min-w-0 [&>div]:shrink [&_p]:max-w-sm">
          <span ref={setSlot} className="contents" data-testid="bar-slot" />
          {pr && !readOnly && (
            <ApproveDenyActions key={pr.url} pr={pr} inDetail onApproved={reload} onDenied={() => { reload(); onBack?.() }} />
          )}
          {pr && readOnly && (
            <span data-readonly="1" className="rounded px-2 py-1 text-xs bg-neutral-800 text-neutral-300">{(pr.state || 'closed').toLowerCase()} · read-only</span>
          )}
        </div>
      </div>

      <div>
        <h2 className="break-words text-xl font-semibold text-white [overflow-wrap:anywhere]" data-testid="item-title">{title}</h2>
        <p className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-neutral-500" data-testid="item-meta">
          {item.project && <span className="inline-block rounded border border-neutral-700 px-1.5 text-[11px] leading-4 text-neutral-300">{item.project}</span>}
          {ticketNumber != null && <span>ticket #{ticketNumber}</span>}
          {pr && <><span aria-hidden="true">·</span><a href={pr.url} target="_blank" rel="noreferrer" className="hover:text-neutral-300">PR #{pr.number}</a></>}
          {/* A ticket with more than one open PR: the others, one tap to lead the page instead. */}
          {item.others.map((o) => (
            <span key={o.number}><span aria-hidden="true">· </span>
              <button type="button" data-other-pr={o.number} onClick={() => onOpenItem?.({ repo, pr: o.number })} className="text-sky-400 hover:text-sky-300">also PR #{o.number}</button>
            </span>
          ))}
          {ticketNumber == null && pr && <span>· no ticket</span>}
        </p>
      </div>

      <LifeStrip stages={stages} />

      {pr?.refusal && (
        <div data-refusal="1" className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          Approve refused {new Date(pr.refusal.at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}: <strong>{pr.refusal.reason}</strong>
          {pr.refusal.message && <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-red-300/80">{pr.refusal.message}</p>}
        </div>
      )}

      {/* The current stage's content first: the pictures (I1), then the Decisions. */}
      {pr && (pr.images?.length > 0 || pr.mockups?.length > 0) && (
        <Card title={`Images${pinned ? ` · pinned to ${pinned}` : ''}`} testid="item-images">
          <MockupLauncher pr={pr} />
          {pr.images?.length > 0 && <PrImages images={pr.images} size="small" anchorPrefix={GALLERY} limit={GALLERY_LIMIT} />}
        </Card>
      )}
      {pr && !readOnly && !pr.images?.length && pr.needsImages && <NeedsImages needsImages={pr.needsImages} />}
      {pr && !readOnly && pr.images === undefined && <p className="text-sm text-neutral-500" data-testid="images-loading">Reading the PR’s images…</p>}

      {decisions && (
        <div id={DECISIONS_ANCHOR} className="scroll-mt-4" data-testid="item-decisions">
          <Decisions
            key={JSON.stringify(decisions.questions.map((q) => [q.id, q.question, q.options.map((o) => o.label)]))}
            repo={repo}
            number={pr && !readOnly ? pr.number : ticketNumber}
            decisions={decisions}
            refsFor={(q) => imageRefsFor(q.question, pr?.images)}
            onSeeImage={(index) => showImage(GALLERY, index)}
            submitSlot={slot}
            onSubmitted={reload}
          />
        </div>
      )}

      {ticketNumber != null && (
        <TicketCard repo={repo} number={ticketNumber} detail={detail} error={ticketRead.error && !detail ? ticketRead.error : null}
          stripDecisions={!!ticketDecisions?.present} onLink={onLink} onSent={reload} />
      )}

      {pr && <PrDetails pr={pr} onOpenTicket={(r, n) => onOpenItem?.({ repo: r, ticket: n })} onOpenDocs={onOpenDocs} />}

      <ItemHistory rows={rows} now={now} />

      {/* Related's own top rule and margin give way to the card's (mock-up: a box like the others). */}
      <div className="rounded-lg border border-neutral-800 bg-neutral-900/70 px-4 pb-3 [&>section]:mt-0 [&>section]:max-w-none [&>section]:border-t-0 [&>section]:pt-3 [&>p]:mt-0 [&>p]:py-3" data-testid="item-related">
        <Related
          rel={rel}
          onDoc={(project, path) => onOpenDocs?.(project, path)}
          onTicket={(r, n) => onOpenItem?.({ repo: r, ticket: n })}
          onPr={(r, n) => onOpenItem?.({ repo: r, pr: n })}
        />
      </div>
    </div>
  )
}

function BackLink({ onBack }) {
  return (
    <button type="button" onClick={onBack} className="self-start text-sm text-neutral-400 hover:text-neutral-200" data-testid="item-back">
      ← Now
    </button>
  )
}

// MR Review's other sections (what it is, the evidence or description), folded under one line.
function PrDetails({ pr, onOpenTicket, onOpenDocs }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900/70" data-testid="item-pr-details" data-open={open ? 'yes' : 'no'}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="w-full px-4 py-3 text-left text-sm font-semibold text-neutral-400 hover:text-neutral-200">
        {open ? '▾' : '▸'} PR #{pr.number} details
      </button>
      {open && (
        <div className="flex flex-col gap-4 px-4 pb-4">
          {pr.summary && <SummarySection summary={pr.summary} repo={pr.repo} headRef={pr.headRef} onOpenTicket={onOpenTicket} onOpenDocs={onOpenDocs} />}
          <PrEvidenceSections pr={pr} onOpenTicket={onOpenTicket} onOpenDocs={onOpenDocs} />
        </div>
      )}
    </section>
  )
}
