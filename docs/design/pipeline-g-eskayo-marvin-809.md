Now I have everything needed. Here's the plan.

## North-star fit

Reuses, before adding anything: the preflight-refusal pattern (`assertTargetsBase`/`assertNotSentBack`/`readyIfDraft` in `merge.js`, each a cheap `gh pr view` + `refusal()` + `throw MergeFailure`); the shared-snapshot pattern (`pr_snapshot.js`'s `snapshotExec`, P5) for the new `state` read; the existing fan-out pattern (`createMergeTracker`'s `emit`, `stageFanOut`) as the template for broadcasting one merge's events to more than one listener; and the existing `createMergeLatch`/`alreadyMergingBody` pair in `merge_progress.js`, which this extends rather than replaces. No new abstraction layer, no new persistence format — just one new small function pair (`assertStillOpen`, `createMergeJoin`) that follows shapes already in the file.

Simplest sufficient approach: the dedupe only needs to cover a PR URL that is **actively running** the gate on this webhook — that's the concrete bug ("the second run repeats the checks and fails at `gh pr merge`"). A PR merely queued behind a different PR in the same repo is already deduped correctly today (`merge_queue.js`'s `store.add` keeps one item per URL); its response is a position report, not a second gate run, so it's out of scope here — extending joining to that case too would need the persisted queue to carry live reply handles, which is a materially bigger, crash-unsafe change for a case that isn't the reported bug.

Spends a little: one extra `gh pr view --json state` field (folded into the existing shared snapshot read, so no extra `gh` call in the common case) and a small in-memory joiner map, cleared the moment each attempt ends (O(1) per merge, no persistence, no leak).

Leaves the user more capable: no behavior to learn, no new button — Approve just stops lying when clicked twice (two Macs, or a reconnect after a drop), and stops burning ~40 minutes of gate time on a PR that's already merged.

Machine: runs on whichever Mac's webhook is already running the merge gate (no change to where this runs).

One correctness finding changes the design from "join everywhere" to "join only the plain click path": `approval_retry.js`'s `pass()` awaits `approve()` for each waiting ledger entry **sequentially**, and a retry/pinned-machine retry explicitly depends on getting `ALREADY_MERGING` back fast (`stillInterrupted`/`stillQueuedThere` in `approve_flow.js`) so the pass can move to the next waiting entry. If a retry-flagged request instead joined and blocked for the gate's full duration (up to 40 min), one slow entry would stall every other waiting approval behind it in that pass — a real regression, not a style choice. So the fix threads a `probe` flag through the one caller that needs the old fast-refuse (`approval_retry.js`, via `retry: true`) and the existing internal `by: 'memory-queue'` trigger, and joins everyone else (a plain click, a second Mac's click, a click after a dropped stream — none of which set `retry`).

No owner decision is needed — the one real fork (join everywhere vs. keep retry fast) was resolved by the evidence above, not a preference.

## Tests first

**merge.js — `assertStillOpen`** (new, mirrors `assertNotSentBack`'s existing test block in `merge.test.js`):
1. `state: 'MERGED'` → rejects with `payload.code === 'ALREADY_MERGED'`, message containing "already merged" (AC2's literal wording).
2. `state: 'CLOSED'` → rejects with a distinct code (e.g. `PR_CLOSED`), message saying it was closed, not merged.
3. `state: 'OPEN'` → resolves (no throw).
4. `gh pr view` rejects (network/transient) → resolves (fails open, same policy as `assertTargetsBase`).
5. Malformed JSON / missing `state` field → resolves (fails open), doesn't throw a parse error.
6. Ordering: a PR that is both on the wrong base **and** merged fails with `ALREADY_MERGED`, not `WRONG_BASE` — proves it runs first, before `assertTargetsBase`, before `gateContext`.
7. `mergePr(prUrl, ...)` end-to-end on a merged PR: rejects with `ALREADY_MERGED` and never reaches `gh pr merge` (assert on the exec mock's call list, mirroring the existing `SENT_BACK` end-to-end test at line 1182).

**pr_snapshot.js:**
8. `state` is servable from the one combined snapshot read — a preflight sequence that reads `state` then `baseRefName`/`body`/etc. makes exactly one `gh pr view` call (extends the existing P5 call-count test).

**merge_progress.js — `createMergeJoin`** (new describe block, next to `createMergeLatch`'s in `merge_failover.test.js` or `merge_progress.test.js`):
9. Two mock replies joined on the same URL both receive every `.event()` call fired for that URL, in order.
10. Three joined replies all receive the identical `.result(status, body)` call once, and the entry is removed afterward (map is empty — no leak).
11. A reply joined on URL A is never called when events/result fire for URL B (keyed correctly, no cross-talk).
12. `.result()` on a joiner whose connection already closed doesn't throw (relies on `approveResponder`'s existing `writableEnded`/`destroyed` guards — a joiner is just another reply).

**index.js wiring (new test, alongside the existing hand-rolled webhook harness in `merge_failover.test.js`, lines ~492-516):**
13. Two `/approve` POSTs for the same URL while the first is mid-gate (`mergeQueue.isRunning` true), neither carrying `probe`: exactly one `gh pr merge`-equivalent run happens; both streams end on the same `{merged: true, ...}` result.
14. Same setup but the run fails (sent back / gate test failure): both streams end on the same failure body — not one succeeding and one timing out.
15. A third, later join after the second has already joined: fan-out to all three, same result.
16. A request carrying `probe: true` (or `by: 'memory-queue'`) hitting an already-running URL: gets the old fast `409 ALREADY_MERGING` immediately, same as today — **and the existing test at `merge_failover.test.js:492` ("the stream dropped but the Mini is still merging it...the retry is refused ALREADY_MERGING") must keep passing unmodified**, since it's the regression guard for `approval_retry.js`'s sequential-pass assumption.
17. A second approve for a **different** PR in the same repo while the first is running: unaffected — queued normally with its own place (dedupe is keyed by URL, not by repo).
18. Repeats/concurrency: three near-simultaneous (same tick, no intervening `await`) requests for one URL — `isRunning` check and `join()` call happen back-to-back with no await between them, so there's no window where a late joiner registers after `finish()` already cleared the map; test this directly by asserting the join call always succeeds when `isRunning()` was true in the same synchronous step.
19. **"Approve, deny, approve within a second"** (the ticket's explicit break-it case): approve starts the gate; deny (`drop`) closes the PR on GitHub mid-gate; a second approve for the same URL joins; when the gate's own `gh pr merge` eventually fails because the PR is closed, both the original and the joined stream end on that same failure, and the deny's own response is unaffected (it doesn't wait on the gate at all).
20. A stale/person's-mistake case: approving a PR URL that's well-formed but doesn't exist (`PR_NOT_FOUND`) twice in a row — both get refused the same way; no hang, no leaked joiner entry.
21. Wrong permissions / each dependency failing: `gh pr view --json state` fails because the token is invalid (`GH_AUTH_INVALID`) — `assertStillOpen` fails open (test 4 above) and the *real* auth failure still surfaces later, at whichever check actually needs `gh` to succeed, unchanged from today.

**approve_stream.js / approve_flow.js (client side):**
22. `approveMrStream` includes `probe: true` in the POST body only when called with `{probe: true}`; omits it otherwise (so a plain click's wire body is unchanged from today — no behavior change for anything that doesn't opt in).
23. `approve_flow.js` passes `probe: retry` on both the primary `send` call and the `backupForMemory` failover `send` call.

## Task List

1. `merge.js`: add `assertStillOpen(prUrl, exec)` — `gh pr view --json state`, refuse `ALREADY_MERGED` / `PR_CLOSED` via the existing `refusal()` + `MergeFailure` pattern, fail open on any read/parse error. Call it first in `mergePrUnqueued`, before `progress('fetching', 'running')` and before `gateContext`.
2. `pr_snapshot.js`: add `'state'` to `SNAPSHOT_FIELDS` so this new read folds into the existing one-call snapshot.
3. `merge.test.js`: tests 1–7 above.
4. `pr_snapshot.test.js` (or wherever the existing P5 call-count test lives): test 8.
5. `merge_progress.js`: add `createMergeJoin()` next to `createMergeLatch`/`alreadyMergingBody` — `join(url, reply)`, `event(url, ev)`, `finish(url, status, body)` (clears the url's entry).
6. `merge_failover.test.js` (or `merge_progress.test.js`): tests 9–12.
7. `index.js`: instantiate `mergeJoin = createMergeJoin()`; in the `/approve` handler, compute `probe = payload?.probe === true || payload?.by === 'memory-queue'` and, when `mergeQueue.isRunning(prUrl)` is true, branch on `probe` (old 409 path) vs. `mergeJoin.join(prUrl, reply)` (new path, return without responding further) — keep the `isRunning` check and the `join` call adjacent with no `await` between them.
8. `index.js`: in `runMerge`'s tracker `emit`, also call `mergeJoin.event(prUrl, ev)`; at both `return` points (success and catch), call `mergeJoin.finish(prUrl, status, body)` before returning.
9. New or extended test file alongside `merge_failover.test.js`'s existing webhook-harness tests: tests 13–21.
10. `approve_stream.js`: accept a `probe` option; include `probe: true` in the request body only when set.
11. `approve_flow.js`: pass `probe: retry` on the primary `send(...)` call (line ~94) and the `backupForMemory` failover `send(...)` call (line ~100).
12. `approve_stream.test.js` / `approve_flow.test.js` (whichever currently covers these): tests 22–23.
13. Run the full merge/dashboard-webhook suite (not just the new files) to confirm nothing in `merge_queue.test.js`, `merge_memory_wait.test.js`, or `merge_memory_guard.test.js` regresses — those exercise the `ALREADY_MERGING`/`by: 'memory-queue'` paths this change must leave untouched.
14. Screenshots: not expected to be needed — this is a backend dedupe/preflight fix with no new UI states or strings; `MergeProgress.jsx` and the card components are unchanged, just driven by correct events. Re-check once implemented: if any dashboard-visible text or state actually changes, pin 900px and 1440px screenshots on the PR per AC3.