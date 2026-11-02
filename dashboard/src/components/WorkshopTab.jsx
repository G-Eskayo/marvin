import { useCallback, useEffect, useRef, useState } from 'react'
import { buildNow, durationText, stripFor } from '../lib/next_step.js'
import { NOW_TOPICS, loadSaved, readEvents, readSources, save } from '../lib/workshop_feed.js'

// Workshop (ADR 0080, #862): the merge of Activity and MR Review. Only its Now view is built; Projects, Shipped and
// Proposals point at today's screens until #864. Built to the approved mock-up (marvin-instance
// docs/screenshots/review-tab-now-{1440,860}.png).

const storage = () => {
  try { return globalThis.localStorage } catch { return null }
}

// The Now feed, read on mount and on every trigger that changes it (mr:refresh, board/activity/agents/queue pings).
// No timer. App owns it so the tab's dot counts "Your move" while another tab is open.
export function useWorkshopNow() {
  const [state, setState] = useState(() => {
    const saved = loadSaved(storage())
    return saved ? { value: saved.value, events: saved.events, at: saved.at, failed: [], loaded: false, saved: true } : { value: null, events: new Map(), at: null, failed: [], loaded: false, saved: false }
  })
  const latest = useRef(state)
  latest.current = state
  const running = useRef(null)

  const load = useCallback(() => {
    if (running.current) return running.current
    const api = globalThis.window?.api
    if (!api?.mr || !api?.activity?.openTickets || !api?.queue) return Promise.resolve()
    running.current = (async () => {
      try {
        const { value, failed } = await readSources(api, latest.current.value || undefined)
        const events = await readEvents(api, value)
        const now = Date.now()
        const at = failed.length ? latest.current.at : now
        if (!failed.length) save(storage(), value, events, now)
        setState({ value, events: events.size || !failed.length ? events : latest.current.events, at, failed, loaded: true, saved: latest.current.saved })
      } catch {
        setState((s) => ({ ...s, failed: ['everything'], loaded: true }))
      } finally {
        running.current = null
      }
    })()
    return running.current
  }, [])

  useEffect(() => {
    load()
    const api = globalThis.window?.api
    const offMr = api?.mr?.onRefresh?.(load) || (() => {})
    const offTrigger = api?.triggers?.on?.((t) => NOW_TOPICS.has(t?.topic) && load()) || (() => {})
    return () => { offMr(); offTrigger() }
  }, [load])

  const now = state.value ? buildNow({ ...state.value, events: state.events }) : null
  return { ...state, now, reload: load }
}

const VIEWS = [
  ['now', 'Now'],
  ['projects', 'Projects'],
  ['shipped', 'Shipped'],
  ['proposals', 'Proposals']
]

export function WorkshopControl({ onPick }) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-lg border border-neutral-800 p-1" role="tablist">
      {VIEWS.map(([id, label]) => (
        <button key={id} role="tab" aria-selected={id === 'now'} onClick={() => onPick(id)}
          className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${id === 'now' ? 'bg-neutral-800 text-white' : 'text-neutral-400 hover:text-neutral-200'}`}>
          {label}
        </button>
      ))}
    </div>
  )
}

function Section({ title, aside, children, testid }) {
  return (
    <section className="mt-6" data-testid={testid}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-neutral-400">{title}</h2>
        <span className="text-xs font-medium text-neutral-500">{aside}</span>
      </div>
      {children}
    </section>
  )
}

const Box = ({ tone, children }) => (
  <div className={`divide-y overflow-hidden rounded-lg border ${tone === 'stuck' ? 'divide-red-900/40 border-red-900/60 bg-red-950/40' : 'divide-neutral-800 border-neutral-800 bg-neutral-900/70'}`}>{children}</div>
)

const VERB_TONE = { stuck: 'text-red-400', yours: 'text-amber-400', marvin: 'text-sky-400', next: 'text-neutral-300' }
const BAR = { passed: 'bg-emerald-700', running: 'bg-sky-400', failed: 'bg-red-500', stalled: 'bg-amber-500', 'needs-rebase': 'bg-amber-500', skipped: 'bg-neutral-700', pending: 'bg-neutral-800' }

function Chip({ project }) {
  if (!project) return null
  return <span className="mr-1.5 inline-block rounded border border-neutral-700 px-1.5 text-[11px] leading-4 text-neutral-300">{project}</span>
}

const clock = (ms) => (ms == null ? null : new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }))

// What follows the chip on the grey line, in the mock-up's order.
export function metaFor(item, section, now = Date.now()) {
  const parts = []
  const pr = item.pr
  if (section === 'next') {
    parts.push(`#${item.number}`)
    if (item.priority) parts.push(item.priority)
    if (item.step.verb === 'Rework') parts.push('sent back')
    return parts
  }
  if (section !== 'marvin' && section !== 'stuck' && item.priority) parts.push(item.priority)
  if (item.type === 'pr') {
    parts.push(`PR #${item.number}`)
    if (item.ticketNumber != null) parts.push(`closes #${item.ticketNumber}`)
  } else if (item.type === 'ticket') {
    parts.push(`#${item.number}`)
  } else {
    parts.push('proposal')
  }
  if (section === 'yours') {
    if (item.type === 'ticket') parts.push('ticket', item.step.verb === 'Give info' ? 'needs-info' : 'ready-for-human')
    if (pr?.checks?.state === 'passing') parts.push('checks passed')
    if (pr?.mockups?.length) parts.push('mock-up')
    if (pr?.mergeQueue?.reason && item.step.verb !== 'Approve') parts.push(pr.mergeQueue.reason)
  }
  if (section === 'marvin') {
    const runs = pr?.checks?.runs
    if (item.step.verb === 'Checks running' && Array.isArray(runs) && runs.length) parts.push(`GitHub checks ${runs.filter((r) => r.state && r.state !== 'pending').length} of ${runs.length}`)
    if (item.step.verb === 'Being fixed') parts.push('sent back, fix in progress')
    if (pr?.mergeQueue?.reason && /queue|Merging/.test(item.step.verb)) parts.push(pr.mergeQueue.reason)
    if (item.worker) parts.push(item.worker)
    const ran = durationText(item.startedAt, now)
    if (ran) parts.push(ran)
  }
  if (section === 'stuck') {
    if (item.worker) parts.push(`held on ${item.worker}`)
    parts.push(item.step.verb.toLowerCase())
    const since = clock(item.step.stuckSince)
    if (since && /movement|failed/.test(item.step.verb)) parts.push(`no movement since ${since}`)
  }
  return parts
}

export function leftLabel(item, section, now = Date.now()) {
  if (section === 'stuck') {
    const d = durationText(item.step.stuckSince, now)
    return `Stuck${d ? ` ${d}` : ''} · ${item.step.owner === 'marvin' ? 'MARVIN' : 'nobody'}`
  }
  return item.step.verb
}

function rightLabel(item, section, now) {
  if (section === 'yours') {
    const d = durationText(item.since, now)
    return d ? `waiting ${d}` : null
  }
  if (section === 'marvin') return item.step.phase
  if (section === 'next') return 'ready'
  return null
}

function Row({ item, section, onOpen, now }) {
  const strip = section === 'marvin' ? stripFor(item, now) : []
  return (
    <button onClick={() => onOpen(item)} data-testid="now-row" data-section={section}
      className="flex w-full min-w-0 flex-col gap-2 px-4 py-3 text-left hover:bg-white/[0.03] lg:flex-row lg:items-center lg:gap-0">
      <span className={`shrink-0 text-sm font-semibold lg:w-[164px] ${VERB_TONE[section]}`}>{leftLabel(item, section, now)}</span>
      <span className="flex min-w-0 flex-1 items-center gap-4">
        <span className="min-w-0 flex-1">
          <span className="block break-words text-sm text-neutral-100 [overflow-wrap:anywhere]">{item.title}</span>
          <span className="mt-0.5 block break-words text-xs text-neutral-500 [overflow-wrap:anywhere]">
            <Chip project={item.project} />
            {metaFor(item, section, now).join(' · ')}
          </span>
          {strip.length > 0 && (
            <span className="mt-1.5 flex gap-1" aria-label="stages">
              {strip.map((s, i) => <span key={i} className={`h-[3px] w-[22px] rounded-sm ${BAR[s] || BAR.pending}`} />)}
            </span>
          )}
        </span>
        <span className="shrink-0 text-xs text-neutral-400">{rightLabel(item, section, now)}</span>
      </span>
    </button>
  )
}

function Empty({ children }) {
  return <p className="px-4 py-3 text-sm text-neutral-500">{children}</p>
}

export function WorkshopNow({ feed, onOpen, now = Date.now() }) {
  const [moreOpen, setMoreOpen] = useState(false)
  const data = feed.now
  const stale = feed.failed?.length > 0
  if (!data) {
    return feed.loaded
      ? <p className="mt-6 text-sm text-red-400">Can’t reach GitHub ({feed.failed.join(', ')}), and nothing is saved from an earlier read yet.</p>
      : <p className="mt-6 text-sm text-neutral-500">Loading…</p>
  }
  const { stuck, yours, marvin, next } = data.sections
  const asOf = feed.at ? new Date(feed.at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : null
  const rows = (list, section) => list.map((item) => <Row key={item.key} item={item} section={section} onOpen={onOpen} now={now} />)
  return (
    <div>
      {stale && (
        <p className="mt-4 rounded-md border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-300" data-testid="as-of">
          Can’t read {feed.failed.join(', ')} right now: showing the last known list{asOf ? `, as of ${asOf}` : ''}.
        </p>
      )}
      {stuck.length > 0 && (
        <Section title="Stuck" aside="nobody’s move, or over its limit (I5)" testid="now-stuck">
          <Box tone="stuck">{rows(stuck, 'stuck')}</Box>
        </Section>
      )}
      <Section title="Your move" aside={`priority, then oldest wait · ${yours.length}`} testid="now-yours">
        <Box>{yours.length ? rows(yours, 'yours') : <Empty>{stale ? 'Nothing waiting on you in the last known list.' : 'Nothing waiting on you.'}</Empty>}</Box>
      </Section>
      <Section title="MARVIN is on it" aside={`all ${marvin.length} · everything in motion`} testid="now-marvin">
        <Box>{marvin.length ? rows(marvin, 'marvin') : <Empty>Nothing in motion.</Empty>}</Box>
      </Section>
      <Section title="Up next" aside="the pipeline’s queue" testid="now-next">
        <Box>
          {next.length === 0 && <Empty>Nothing ready.</Empty>}
          {rows(moreOpen ? next : next.slice(0, 1), 'next')}
          {next.length > 1 && (
            <button onClick={() => setMoreOpen(!moreOpen)} className="w-full px-4 py-3 text-left text-sm text-neutral-400 hover:text-neutral-200">
              {moreOpen ? '▾ fewer' : `▸ ${next.length - 1} more ready`}
            </button>
          )}
        </Box>
      </Section>
      <p className="mt-3 text-xs text-neutral-500">Machines, helpers’ health and the parallel toggle: Health.</p>
    </div>
  )
}

export default function WorkshopTab({ feed, navigate }) {
  const pick = (id) => {
    if (id === 'projects') navigate('activity')
    else if (id === 'shipped') navigate('mr-review', { view: 'merged' })
    else if (id === 'proposals') navigate('mr-review', { view: 'proposals' })
  }
  // Every row opens today's PR detail or ticket drill-down until the item page lands (#863).
  const open = (item) => {
    if (item.type === 'pr') navigate('mr-review', { prKey: item.key })
    else if (item.type === 'ticket') navigate('activity', { repo: item.repo, ticketNumber: item.number })
    else navigate('mr-review', { view: 'proposals' })
  }
  return (
    <div className="max-w-[1100px] px-4 py-5 lg:px-6" data-testid="workshop">
      <WorkshopControl onPick={pick} />
      <WorkshopNow feed={feed} onOpen={open} />
    </div>
  )
}
