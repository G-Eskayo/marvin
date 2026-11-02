// The Workshop ▸ Now feed (#862): reads the sources next_step.js needs once, on a trigger, never on a timer. A source
// that fails (GitHub unreachable, a store error) keeps its last known value, and the result says as of when, so the
// view never turns an outage into an empty "nothing waiting". Pure apart from the injected api and storage.
import { buildNow } from './next_step.js'
import { readSaved, writeSaved } from './saved_state.js'

export const SAVED_KEY = 'workshop.now'
// Trigger topics that change what the Now view shows (electron/main/index.js triggerHub, refresh server pings).
export const NOW_TOPICS = new Set(['activity', 'agents', 'board', 'mr', 'proposals', 'queue'])
// In-motion rows read their ticket's stage events; bounded so a flood of claims can't fan out into hundreds of reads.
const MAX_TIMELINES = 40

const EMPTY = { prs: [], tickets: [], projects: [], running: [], queue: [], proposals: [] }

// One read of every source. Returns { value, failed: [names] }; value keeps `prev` for each failed source.
export async function readSources(api, prev = EMPTY) {
  const value = { ...EMPTY, ...prev }
  const failed = []
  const [prs, open, queue, proposals] = await Promise.allSettled([
    api.mr.list(),
    api.activity.openTickets(),
    api.queue.list(),
    api.proposals?.list ? api.proposals.list() : Promise.resolve({ ok: true, proposals: [] })
  ])
  if (prs.status === 'fulfilled' && Array.isArray(prs.value)) value.prs = prs.value
  else failed.push('pull requests')
  if (open.status === 'fulfilled' && Array.isArray(open.value?.tickets)) {
    value.tickets = open.value.tickets
    value.projects = Array.isArray(open.value.projects) ? open.value.projects : value.projects
  } else failed.push('tickets')
  if (queue.status === 'fulfilled' && queue.value && !queue.value.error) {
    value.running = queue.value.running || []
    value.queue = queue.value.queue || []
  } else failed.push('the ticket queue')
  if (proposals.status === 'fulfilled' && proposals.value?.ok !== false && Array.isArray(proposals.value?.proposals)) value.proposals = proposals.value.proposals
  else failed.push('proposals')
  return { value, failed }
}

// The stage events of every item MARVIN has in hand (in motion or stuck), keyed "repo#number".
export async function readEvents(api, value, now = Date.now()) {
  const first = buildNow({ ...value, events: new Map() }, now)
  const keys = []
  for (const item of [...first.sections.marvin, ...first.sections.stuck]) {
    const repo = item.repo
    const n = item.type === 'pr' ? item.ticketNumber : item.number
    if (repo && n != null) keys.push([repo, n])
  }
  const events = new Map()
  await Promise.all(keys.slice(0, MAX_TIMELINES).map(([repo, n]) =>
    api.activity.timeline(n, repo).then((ev) => Array.isArray(ev) && events.set(`${repo}#${n}`, ev)).catch(() => {})))
  return events
}

// The heavy parts of a PR card the Now view never reads: left out of the saved copy so it fits in storage.
const UNSAVED_PR_FIELDS = ['rawBody', 'images', 'evidence', 'summary']
const slimPr = (pr) => Object.fromEntries(Object.entries(pr || {}).filter(([k]) => !UNSAVED_PR_FIELDS.includes(k)))

export function loadSaved(storage) {
  const saved = readSaved(storage, SAVED_KEY)
  if (!saved || typeof saved.value !== 'object' || !saved.value) return null
  const { events = [], ...value } = saved.value
  let map
  try { map = new Map(Array.isArray(events) ? events : []) } catch { map = new Map() }
  const clean = Object.fromEntries(Object.entries(EMPTY).map(([k, d]) => [k, Array.isArray(value[k]) ? value[k] : d]))
  return { value: clean, events: map, at: saved.at }
}

export function save(storage, value, events = new Map(), now = Date.now()) {
  writeSaved(storage, SAVED_KEY, { ...value, prs: (value.prs || []).map(slimPr), events: [...events] }, now)
}
