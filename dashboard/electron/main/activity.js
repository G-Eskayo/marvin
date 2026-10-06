import { listAllTrackedTickets, readStages } from '../../webhook-server/ticket_stages.js'
import { readDispatchStatus } from './dispatch_status.js'

// Activity tab (G-Eskayo/marvin#113-117's scope) -- a per-ticket pipeline
// timeline, not just live status, per Gil's 2026-10-01 ask: this is meant
// to make a failure's actual stage ("where did it break") a queryable
// fact instead of something that has to be forensically re-traced by hand
// (exactly what finding PR #119's real failure point required before
// ticket_stages.py/.js existed).
const TERMINAL_STAGE_ORDER = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'rebuilding', 'done']

function summarize(events) {
  if (events.length === 0) return { currentStage: null, currentStatus: null, costUsd: 0, failed: false, title: null }
  const last = events[events.length - 1]
  const costUsd = events.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
  const failed = events.some((e) => e.status === 'failed')
  // Title is only ever set on the event that had it available (usually
  // "claimed", the first) -- take the first one found, not the last.
  const title = events.find((e) => e.title)?.title || null
  return { currentStage: last.stage, currentStatus: last.status, costUsd, failed, title }
}

const MARVIN_REPO = 'G-Eskayo/marvin'

// The dispatch label is `ticket #N: ...` for marvin and `ticket <owner/repo>#N: ...` for any other project, so a
// bare "#13" appears in both. Match the right form, and not "#130" when asked about #13.
function taskIsTicket(task, repo, number) {
  if (!task) return false
  const n = String(number)
  const form = repo === MARVIN_REPO ? `ticket #${n}` : `${repo}#${n}`
  const at = task.indexOf(form)
  if (at < 0) return false
  return !/\d/.test(task.charAt(at + form.length))
}

export function listTicketActivity(statePath, stagesDir) {
  const tickets = listAllTrackedTickets(stagesDir)
  const liveDispatch = readDispatchStatus(statePath)
  return tickets.map(({ repo, number }) => {
    const events = readStages(number, stagesDir, repo)
    const summary = summarize(events)
    return {
      repo,
      number,
      key: `${repo}#${number}`,
      ...summary,
      eventCount: events.length,
      lastEventAt: events.length ? events[events.length - 1].timestamp : null,
      isLiveNow: !!(liveDispatch.busy && taskIsTicket(liveDispatch.task, repo, number))
    }
  }).sort((a, b) => {
    // In-flight tickets first, then most-recently-active.
    if (a.isLiveNow !== b.isLiveNow) return a.isLiveNow ? -1 : 1
    return (b.lastEventAt || '').localeCompare(a.lastEventAt || '')
  })
}

// One ticket's history. `repo` is required to be right for any project other than marvin (null means marvin).
export function getTicketTimeline(number, stagesDir, repo = null) {
  return readStages(number, stagesDir, repo)
}

export { TERMINAL_STAGE_ORDER }
