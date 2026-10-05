// What MARVIN is doing right now on this machine, for the header indicator: a task launched through
// the dispatch system (a pipeline ticket, a research run) plus every background agent whose run log
// says it is mid-run (lib/job_events.py). The old indicator only knew about the first kind, which is
// why it said nothing while the hourly scan, catalog refresh or tidy agent were running.
export function buildWorkingNow({ dispatch, jobs }) {
  const items = []
  if (dispatch?.busy) items.push({ kind: 'task', label: dispatch.task || 'a dispatched task', detail: '', startedAt: dispatch.startedAt })
  for (const j of jobs) {
    if (j.status !== 'running' || !j.current) continue
    items.push({
      kind: 'job',
      label: j.label,
      detail: j.current.detail ? `${j.current.step} — ${j.current.detail}` : j.current.step,
      startedAt: j.current.startedAt
    })
  }
  const finished = jobs.filter((j) => j.last?.finishedAt).sort((a, b) => b.last.finishedAt.localeCompare(a.last.finishedAt))
  const last = finished.length ? { label: finished[0].label, finishedAt: finished[0].last.finishedAt, summary: finished[0].last.summary || '' } : null
  return { items, last }
}
