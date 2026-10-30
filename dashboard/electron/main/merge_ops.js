import { emptyProgress, applyMergeEvent, opForHead, closeRunning } from '../../src/lib/merge_progress.js'
import { repoFromPrUrl } from './mr_repos.js'

// What each PR's Approve & Merge is doing right now, held in the main process so it survives the
// renderer unmounting (navigating away used to reset the button to "Approve & Merge" mid-merge).
// Failures and re-engagements are kept until the next attempt so the message is still there on return -- but only for
// the commit they happened on: once the PR has a newer head, the old failure no longer describes it (Gil, 2026-10-21).
//
// marvin#568: the op also carries the merge's progress, folded from the stage events the webhook pushes (on the
// approve response's stream, and through the local refresh ping for a merge started elsewhere). The card reads the op
// once when it mounts, then gets every change pushed (index.js sends 'mr:mergeEvent'); nothing re-reads on a timer.
export const INTERRUPTED_REASON = 'The merge was interrupted when the webhook restarted. Approve again.'
const KEEP_FINISHED_MS = 24 * 3600_000

export function createMergeOps({ maxMergingMs = 45 * 60_000 } = {}) {
  const ops = new Map()
  // A merge that never reports back (a hung gate) must not read "Merging…" forever: past the limit since its last
  // event it is an error, and a new attempt may start. Counted from the last event, so a long gate that keeps
  // reporting (busy machine, extended limit) is not given up on.
  const live = (url, now) => {
    const o = ops.get(url)
    if (o && o.state === 'merging' && now - (o.lastEventAt ?? o.since) > maxMergingMs) {
      const expired = { state: 'error', reason: 'The merge did not finish within the time limit and was given up on. Approve again to retry.', head: o.head ?? null, progress: closeRunning(o.progress, 'failed', 'no word from the webhook', now), at: now }
      ops.set(url, expired)
      return expired
    }
    return o
  }
  // A PR merged on GitHub stays merged, whatever the webhook answers afterwards.
  const mergedHere = (url) => ops.get(url)?.state === 'merged'
  const prune = (now) => {
    for (const [url, o] of ops) if (o.state !== 'merging' && o.at != null && now - o.at > KEEP_FINISHED_MS) ops.delete(url)
  }
  return {
    start(url, now = Date.now(), head = null) {
      if (live(url, now)?.state === 'merging') return false
      prune(now)
      ops.set(url, { state: 'merging', since: now, head, progress: emptyProgress(), lastEventAt: now })
      return true
    },
    // Fold one stage event in. Returns the op when it changed (push it), or null (duplicate, late, junk, another
    // attempt's). A merge this window did not start is adopted, so its card shows it and cannot start another.
    event(url, ev, now = Date.now()) {
      let o = live(url, now)
      if (!o || o.state !== 'merging') {
        // After a finished attempt, only a new attempt's first event (seq 1, another id) starts a new op: anything
        // else is a straggler from the finished one and must not resurrect it.
        if (o && (ev?.seq !== 1 || !ev?.id || ev.id === o.progress?.id)) return null
        o = { state: 'merging', since: now, head: null, progress: emptyProgress(), lastEventAt: now, adopted: true }
      }
      const progress = applyMergeEvent(o.progress, ev)
      if (progress === o.progress) return null
      let next = { ...o, progress, lastEventAt: now }
      if (ev.interrupted) next = { state: 'interrupted', reason: INTERRUPTED_REASON, head: o.head ?? null, progress: closeRunning(progress, 'failed', 'interrupted: the webhook restarted', now), at: now }
      else if (o.adopted && progress.outcome === 'merged') next = { state: 'merged', head: o.head ?? null, progress, at: now }
      else if (o.adopted && progress.outcome === 'failed') next = { state: 'error', reason: progress.stages[ev.stage]?.detail || 'The merge failed.', head: o.head ?? null, progress, at: now }
      ops.set(url, next)
      return next
    },
    finish(url, result, now = Date.now()) {
      if (mergedHere(url)) return ops.get(url)
      const o = ops.get(url)
      const base = { head: o?.head ?? null, progress: o?.progress, at: now }
      ops.set(url, result?.reengaged ? { state: 'reengaged', reason: result.reason, ...base } : { state: 'merged', ...base })
      return ops.get(url)
    },
    fail(url, reason, now = Date.now()) {
      if (mergedHere(url)) return ops.get(url)
      const o = ops.get(url)
      ops.set(url, { state: 'error', reason, head: o?.head ?? null, progress: closeRunning(o?.progress, 'failed', null, now), at: now })
      return ops.get(url)
    },
    // The approve stream ended with no result: the webhook went away mid-merge (restart, crash, machine asleep).
    interrupt(url, now = Date.now()) {
      const o = live(url, now)
      if (!o || o.state !== 'merging') return null
      const next = { state: 'interrupted', reason: INTERRUPTED_REASON, head: o.head ?? null, progress: closeRunning(o.progress, 'failed', 'interrupted: the webhook restarted', now), at: now }
      ops.set(url, next)
      return next
    },
    // marvin#762: the plain words for a merge that failed over ("The Mac mini is offline, merging on this MacBook Pro
    // instead."), carried on the running op so the card shows them until it ends. Not merging = nothing changes.
    notice(url, text, now = Date.now()) {
      const o = live(url, now)
      if (!o || o.state !== 'merging') return null
      ops.set(url, { ...o, notice: text })
      return ops.get(url)
    },
    // No machine could take the approval: it is saved (approval_ledger.js) and retried when one comes back. Nothing
    // ran, so there is no progress to show.
    queue(url, reason, now = Date.now()) {
      if (mergedHere(url)) return ops.get(url)
      const o = ops.get(url)
      ops.set(url, { state: 'queued', reason, head: o?.head ?? null, progress: null, at: now })
      return ops.get(url)
    },
    // marvin#940: the machine refused it for memory and queued it; it runs there by itself when pressure drops. Nothing
    // ran, so no progress. `machine` is the machine's name for the card ("Mac mini").
    waitMemory(url, reason, machine = null, now = Date.now()) {
      if (mergedHere(url)) return ops.get(url)
      const o = ops.get(url)
      ops.set(url, { state: 'waiting-memory', reason, machine, head: o?.head ?? null, progress: null, at: now })
      return ops.get(url)
    },
    // Deny cancels a saved approval. One waiting for memory on the Mini is then refused by the Mini's own gate when its
    // queued copy runs (a denied PR is sent back or closed), so nothing merges.
    cancelQueued(url) {
      if (ops.get(url)?.state !== 'queued' && ops.get(url)?.state !== 'waiting-memory') return false
      ops.delete(url)
      return true
    },
    cancel(url) { ops.delete(url) },
    mergingUrls: () => [...ops].filter(([, o]) => o.state === 'merging').map(([url]) => url),
    get(url, now = Date.now(), head = null) {
      return opForHead(live(url, now), head)
    },
    // The change-detector says GitHub changed (for `repo`, or for anything when null). For each merge running here on
    // that repo whose own "Merging on GitHub" has not finished, ask GitHub once whether the PR is already merged: if
    // so the owner merged it on GitHub, and the op ends as "Merged on GitHub" instead of hanging. O(merging ops), and
    // nothing at all while no merge runs. Returns the urls that changed.
    async githubChanged(repo, viewPr, now = Date.now(), only = null) {
      const candidates = [...ops].filter(([url, o]) => o.state === 'merging' && o.progress?.stages?.merging?.state !== 'done' &&
        (!only || only.has(url)) &&
        (!repo || String(repoFromPrUrl(url) || '').toLowerCase() === String(repo).toLowerCase()))
      const changed = []
      for (const [url] of candidates) {
        let state = null
        try { state = (await viewPr(url))?.state } catch { continue }
        const o = ops.get(url)
        if ((state !== 'MERGED' && state !== 'CLOSED') || o?.state !== 'merging') continue
        ops.set(url, state === 'MERGED'
          ? { state: 'merged', elsewhere: true, reason: 'Merged on GitHub', head: o.head ?? null, progress: closeRunning(o.progress, 'skipped', 'merged on GitHub by hand', now), at: now }
          : { state: 'error', reason: 'The PR was closed on GitHub while it was merging.', head: o.head ?? null, progress: closeRunning(o.progress, 'failed', 'closed on GitHub', now), at: now })
        changed.push(url)
      }
      return changed
    }
  }
}
