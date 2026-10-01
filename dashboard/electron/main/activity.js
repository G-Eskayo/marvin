import { listTrackedTickets, readStages } from '../../webhook-server/ticket_stages.js'
import { readDispatchStatus } from './dispatch_status.js'

// Activity tab (G-Eskayo/marvin#113-117's scope) -- a per-ticket pipeline
// timeline, not just live status, per Gil's 2026-10-01 ask: this is meant
// to make a failure's actual stage ("where did it break") a queryable
// fact instead of something that has to be forensically re-traced by hand
// (exactly what finding PR #119's real failure point required before
// ticket_stages.py/.js existed).
const TERMINAL_STAGE_ORDER = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'rebuilding', 'done']

function summarize(events) {
  if (events.length === 0) return { currentStage: null, currentStatus: null, costUsd: 0, failed: false }
  const last = events[events.length - 1]
  const costUsd = events.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
  const failed = events.some((e) => e.status === 'failed')
  return { currentStage: last.stage, currentStatus: last.status, costUsd, failed }
}

export function listTicketActivity(statePath, stagesDir) {
  const tickets = listTrackedTickets(stagesDir)
  const liveDispatch = readDispatchStatus(statePath)
  return tickets.map((number) => {
    const events = readStages(number, stagesDir)
    const summary = summarize(events)
    return {
      number,
      ...summary,
      eventCount: events.length,
      lastEventAt: events.length ? events[events.length - 1].timestamp : null,
      isLiveNow: liveDispatch.busy && liveDispatch.task?.includes(`#${number}`)
    }
  }).sort((a, b) => {
    // In-flight tickets first, then most-recently-active.
    if (a.isLiveNow !== b.isLiveNow) return a.isLiveNow ? -1 : 1
    return (b.lastEventAt || '').localeCompare(a.lastEventAt || '')
  })
}

export function getTicketTimeline(number, stagesDir) {
  return readStages(number, stagesDir)
}

export { TERMINAL_STAGE_ORDER }
