## North-star fit

**Reuses before adding anything new:**
- `prFetchBanner`/`<FetchBanner>` (`dashboard/src/lib/pr_fetch_status.js`, `MrReview.jsx:645`) — the exact "existing FetchBanner style" the ticket asks for; extending it with one more signal rather than building a new banner component.
- The `mr:listStatus` IPC channel and `fetchStatus` state already wired into `OpenPrs` (`MrReview.jsx:667,697`) — no new IPC channel needed.
- `mergeMachines()` (`electron/main/merge_failover.js`) for the down machine's human label ("Mac mini"/"MacBook Pro"), instead of hardcoding a name — same source `approveFlow`'s failover already uses.
- `coalesce()` (already wraps the list builder) for de-duping concurrent list builds — nothing new needed for the "repeats and concurrency" case.
- The `createXxx()` factory convention (`createApprovalLedger`, `createGithubState`, `createTriggerHub`, …) for the new small reachability tracker, so it's unit-testable without module-level global state.
- `describeState`'s existing `notes` composition slot (`prState.js:193`, next to `amNote`) for surfacing the degraded state on a card, instead of adding a new ranked card condition to an already carefully-ordered function.
- `lib/health_checks.py`'s `merge_service_reachable()` reasoning (an HTTP error status still counts as "it answered"; only a network-level failure counts as down) — reused as a *design principle*, not as code: that check runs on a 15-minute cron (`com.marvin.health-check`), far too stale for "list loads in under 4 s" / "clears on the next probe." The Electron-side probe has to be its own (cheap, free) implementation, but follows the same classification rule.

**Simplest sufficient approach:** no 4th network call. `listPipelinePrs` already makes exactly three merge-server reads per list build (`rebaseStatus`, `autoMergeShadow`, `mergeQueue`) — the reachability signal is derived from those, in parallel, for free. The only new code is a ~15-line hysteresis tracker and a few lines of wiring.

**Where it saves/spends tokens:** spends nothing extra at runtime (no added request); saves wall-clock, which is the point — turning three sequential 3 s timeouts into one.

**Phone-OS direction:** N/A directly, but the "trigger-based, never polling" and "flow never hits a wall" rules apply — the banner is derived passively from reads that already happen on every refresh, not a new poll loop, and Approve is never left as a dead end.

**More capable or more passive:** more capable — the owner sees the real state up front instead of discovering it through a failed click, and nothing is taken out of their hands that wasn't already automatic.

**A conflict with a recorded decision, flagged rather than worked around:** this ticket (filed 2026-10-29) proposes disabling Approve when the merge server is down. Later the same day, `marvin#762` shipped a deliberately different, tested design: Approve stays clickable, fails over to another Mac, and failing that **saves the approval and merges it by itself** once a Mac comes back ("Your approval is saved and will merge by itself when it comes back" — `merge_failover.js`, `approval_retry.js`, `prState.js:43-46`). Disabling Approve now would regress that — the owner would have to remember to come back and click again instead of it happening by itself. I'm treating "Approve disabled" as superseded in behavior (kept as a visible Decision below, not silently dropped) and building the banner as an *advance notice* of what #762 already does, not a new block.

## Tests first

From the ticket's "How we'll try to break it":
1. **Server answers the probe but times out on approve** — the three reads succeed (so the tracker reports "up," no banner) while a *separate*, later Approve click still times out; confirms the pre-click reachability signal is independent of, and doesn't mask, the approve-time failover path (`#762`) already covers.
2. **Server flaps every 10 s** — alternating reachable/unreachable reads across several list builds, with a fake clock, must not flicker the banner on every refresh (debounced "down" latch, instant "up" clear).

Additional misuse the section didn't name:
3. All three merge-server reads fail with a real network error (closed port / refused connection, like `merge_failover.test.js`'s `closedPortUrl()`) → tracker reports down, banner shows, list still resolves in one timeout window, not three.
4. Exactly one of the three succeeds (the other two fail) → tracker reports **up** (any answer counts, matching `merge_service_reachable`'s "an HTTPError still answered" rule) — guards the "last call wins" race explicitly: aggregation must be computed once, atomically, from all three settled outcomes, not from independent per-call marks (a naive per-call-mark design flips this wrong depending on Promise resolution order — verified by a test where the *failing* read's promise is made to settle after the succeeding ones').
5. A read answers with malformed/garbage JSON (`res.ok` true, body unparseable) → counts as reachable (server answered, just badly), not down; that read's own data falls back to `{}`/`null` as it already does today.
6. A read answers with a 4xx/5xx → counts as reachable, consistent with #3.
7. Huge/slow response that exceeds the existing 3 s `AbortSignal.timeout` → classified as unreachable, same as a hard network failure.
8. None of the three reads are passed in (the `{light:true}` `mr:reviewStatus` / `mr:historyDetail` paths) → tracker is never consulted and never updated; the list still returns normally.
9. Two overlapping list builds (`mrList()` and `pipelineCardFromMemory()`) report to the tracker concurrently → no corruption, each report is a complete independent observation (no partial/shared mutable batch state).
10. Pull-only box (`ADR 0069`, wrong machine for this feature) → `mergeService` is omitted from `mr:listStatus` entirely; banner never shows, since Approve is already hidden there regardless of merge-server state.
11. The merge server comes back after being down → next successful read clears the tracker immediately ("banner clears on the next probe," no 30 s delay on the *up* path, only on re-declaring *down*).
12. Perf regression guard: with each of the three reads given an equal artificial delay, total wall time for `listPipelinePrs` is bounded by one delay, not the sum of three (proves parallel, not sequential).
13. Existing coverage must still pass unchanged: `mr_review.test.js`'s current rebase/sent-back/closed-ticket tests (a failing `rebaseStatus` still degrades gracefully; a failing `sentBackTickets` still doesn't hide PRs).

## Decisions
<!-- marvin:decisions -->
### approve_when_down: Approve while the merge server is down
- [x] A: Keep Approve enabled. It queues and merges itself once a Mac comes back, matching `#762` (built the same day this ticket was filed). The banner is advance notice, not a block.
- [ ] B: Disable Approve, per this ticket's original acceptance criterion as written. This regresses `#762`'s self-retry: the owner would need to notice the server came back and click Approve again.

## Task List

1. `dashboard/electron/main/merge_service_status.js` (new): `createMergeServiceTracker({ cacheMs = 30_000, now = Date.now })` → `{ report(reached), status() }`, with the hysteresis from tests 1–2/11 (instant clear on reachable, debounced latch on unreachable).
2. `dashboard/test/merge_service_status.test.js` (new): tests 1, 2, 9, 11 against the tracker directly with a fake clock.
3. `dashboard/electron/main/mr_review.js`: in `listPipelinePrs`, replace the sequential `if (x) { try { await x() } catch {} }` blocks for `rebaseStatus`, `sentBackTickets`, `autoMergeShadow`, `closedTickets`, `mergeQueue` with one `Promise.all` of independently-caught reads (kept sequential only where real: `reworkStatus` after `sentBackKeys`). Add an optional `mergeServiceTracker` param; after the three merge-server reads settle, call `mergeServiceTracker?.report(reached)` once (computed from their settled outcomes, not per-call) when at least one was provided, and set `mergeServiceDown: mergeServiceTracker?.status().down ?? false` on each returned PR.
4. `dashboard/test/mr_review.test.js`: extend `listPipelinePrs` tests for cases 3–8, 12, 13.
5. `dashboard/electron/main/index.js`: harden `getRebaseStatus`/`getAutoMergeShadow`/`getMergeQueue` so a `.json()` parse failure returns `{}`/`null` instead of throwing (only a `fetch()`-level failure should count as unreachable — case 5). Construct `mergeServiceTracker = createMergeServiceTracker()`; pass it into both `listPipelinePrs` call sites that already pass the three merge-server reads (`mrList`, `pipelineCardFromMemory`). Compute the down machine's label via the existing `mergeMachines({...})` args already used for `approveFlow`. Extend `mr:listStatus` to return `mergeService: pullOnly ? null : { down: mergeServiceTracker.status().down, label }` (case 10).
6. `dashboard/src/lib/pr_fetch_status.js`: extend `prFetchBanner` to check `mergeService?.down` first, returning `{ tone: 'amber', text: "<label> isn't answering, so approvals will wait." }`, before the existing `source`/`errors` logic.
7. `dashboard/test/github_feed.test.js`: add `prFetchBanner` cases for the new `mergeService` field (priority over `source`/`errors`; null when absent).
8. `dashboard/src/components/MrReview.jsx`: widen the empty-list early-return condition (`:808`) to also show `<FetchBanner>` when `fetchStatus?.mergeService?.down`, so the notice appears even with zero open PRs.
9. `dashboard/src/lib/prState.js`: in the final `'ready'` branch's `notes` array, add a note when `pr.mergeServiceDown` is true (Approve stays `'enabled'`, per the Decision above); comment references both `#762` and `#797`.
10. `dashboard/test/*` (prState): a small test asserting the note appears without changing the `approve` tri-state.
11. Add a real-socket integration test (reusing `merge_failover.test.js`'s `serve()`/`closedPortUrl()` helpers) exercising the full path end-to-end against a genuinely closed port, per the repo's "test against the real collaborator" rule.
12. Run the full dashboard vitest suite; capture before/after screenshots at 900 px and 1440 px of the MR Review list with the merge server down (pin per the acceptance criteria) and with it back up.