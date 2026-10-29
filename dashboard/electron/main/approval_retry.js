// marvin#762: an approval no machine could take is retried when a merge machine comes back, without another click.
// Triggered, never polled (CONTEXT "Triggers over polling"): a webhook starting announces itself (webhook-server
// POST /merge-host-up, relayed to this dashboard as the 'merge-host' topic), this Mac waking or rejoining the network,
// and the dashboard starting. Each trigger runs one pass over the waiting approvals.
//
// A pass, oldest click first: ask GitHub whether the PR is still open (merged or closed by hand meanwhile = settled,
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
      if (state === 'MERGED') { ledger.settle(entry.url, 'merged-elsewhere', { reason: 'merged on GitHub while it waited' }); continue }
      if (state === 'CLOSED') { ledger.settle(entry.url, 'closed', { reason: 'closed on GitHub while it waited' }); continue }
      tried++
      log(`[approval-retry] ${trigger}: retrying the approval of ${entry.url} (clicked ${new Date(entry.clickedAt).toISOString()})`)
      let result
      try { result = await approve(entry.url, entry) } catch (err) {
        log(`[approval-retry] ${entry.url}: ${err?.message || err}`)
        continue
      }
      if (result?.queued) break
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
