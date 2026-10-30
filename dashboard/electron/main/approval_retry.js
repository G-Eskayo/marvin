// marvin#762: an approval no machine could take is retried when a merge machine comes back, without another click.
// So is an interrupted one (owner decision on #766), on the Mac it was interrupted on only.
// Triggered, never polled (CONTEXT "Triggers over polling"): a webhook starting announces itself (webhook-server
// POST /merge-host-up, relayed to this dashboard as the 'merge-host' topic), this Mac waking or being unlocked,
// and the dashboard starting. Each trigger runs one pass over the waiting approvals.
//
// A pass, oldest click first: ask GitHub whether the PR is still open (merged or closed by hand meanwhile = concluded,
// never sent again; GitHub unreachable = leave it for the next trigger), then send it through the same approve path a
// click uses (start the op, record, fail over). The first one that finds no machine ends the pass: the rest would
// only fail the same way. A trigger during a pass runs one more pass after it, never two at once.
// O(waiting) GitHub reads and approve calls per pass.
export function createApprovalRetry({ ledger, approve, viewPr, log = () => {} }) {
  let running = null
  let again = false

  async function pass(trigger) {
    let tried = 0
    for (const entry of ledger.waiting()) {
      let state
      try { state = (await viewPr(entry.url))?.state } catch (err) {
        log(`[approval-retry] ${trigger}: can't check ${entry.url} on GitHub (${err?.message || err}); left queued`)
        continue
      }
      // marvin#940: one waiting for memory was merged by that machine's own queue when pressure dropped.
      if (state === 'MERGED' && entry.outcome === 'waiting-memory') { ledger.conclude(entry.url, 'merged', { machine: entry.machine, reason: 'merged by itself when memory pressure dropped' }); continue }
      if (state === 'MERGED') { ledger.conclude(entry.url, 'merged-elsewhere', { reason: 'merged on GitHub while it waited' }); continue }
      if (state === 'CLOSED') { ledger.conclude(entry.url, 'closed', { reason: 'closed on GitHub while it waited' }); continue }
      tried++
      log(`[approval-retry] ${trigger}: retrying the approval of ${entry.url} (clicked ${new Date(entry.clickedAt).toISOString()})`)
      let result
      // An interrupted one goes back to the Mac it was interrupted on, and only there (approve_flow.js).
      const opts = { number: entry.number, head: entry.head, retry: true, ...(entry.outcome === 'interrupted' ? { machine: entry.machine } : {}) }
      try { result = await approve(entry.url, opts) } catch (err) {
        log(`[approval-retry] ${entry.url}: ${err?.message || err}`)
        continue
      }
      if (result?.queued || result?.waitingMemory) break   // the rest would only wait the same way
    }
    return { tried }
  }

  function run(trigger = 'unknown') {
    if (running) { again = true; return running }
    running = (async () => {
      let out
      do { again = false; out = await pass(trigger) } while (again)
      return out
    })().finally(() => { running = null })
    return running
  }

  return { run }
}
