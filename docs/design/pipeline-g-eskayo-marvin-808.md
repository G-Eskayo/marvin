## North-star fit

**Reuses, before adding anything new:**
- `createInflightStore()` / `inflightPath()` (`dashboard/webhook-server/merge_progress.js:17-61`) — the in-flight file already exists and is already written on every stage change (`createMergeTracker`'s `event()`, line 240) and removed on `end()` (line 253). I only need to *expose* it over HTTP, not invent a new store.
- `GET /merge-progress` (`index.js:229-233`) and `mergeOps.adopt()` (`merge_ops.js:64-79`) — the "catch a card up from a snapshot" mechanism already exists and is already used on app mount/refresh (`catchUpMerges`, `index.js:1052-1064`).
- The webhook→dashboard stage-event relay (`stageFanOut` in `runMerge()`, `index.js:368-382`, delivered via `forwardRefreshPing` → `/refresh` topic `'merge'` → `receiveMergeMessage` → `ops.event()`, `index.js:1434-1439`) — every real stage event of a running merge already reaches the dashboard regardless of which connection originated the Approve. This is the channel that should carry the merge "to its real result"; I don't need to build a second polling loop for that.
- `onSwitch`/`mergeOps.notice()` (`approve_flow.js:45`, `prState.js:214`) — the existing "plain-words notice while merging" channel (used today for "Mac mini offline, merging on this MacBook instead"). I reuse it verbatim for "Lost contact with the Mac mini; checking whether the merge is still running."
- `mergeOps.start()`'s existing re-entrancy guard (`merge_ops.js:36`) and `mergeQueue.isRunning()` 409 guard (`index.js:286-289`) already prevent a true double-merge; I don't need new locking.

**The actual bug** (found by reading the code, not guessable from the issue text alone): `approve_stream.js`'s `interrupted()` fires on *any* stream end/close/error and immediately resolves `{interrupted:true}`. `approve_flow.js` then calls `mergeOps.interrupt(url)`, which sets the op state to `'interrupted'`. But `merge_ops.js`'s `event()` (line 43-59) only revives a non-`'merging'` op on an event with `seq === 1` (a fresh attempt). A still-running merge's *next real stage event* has `seq > 1`, so it's silently dropped (`return null`) — the card is stuck on "interrupted" forever even though the merge is fine. That's the exact failure the ticket describes ("while the merge keeps running").

**Simplest sufficient fix:** don't let a dropped/stalled stream poison `mergeOps`. On drop/stall, ask the new `GET /inflight` once; if the merge is still listed, leave the op in `'merging'` (just post the "Lost contact…" notice) so the *existing* stage-event relay carries it to its real result. If it's not listed, keep today's `interrupted` behavior unchanged. No new polling loop, no new state machine.

**Token/compute cost:** one small new endpoint (reads a file already written), one small client-side reconciliation check (one HTTP GET, only on drop/stall), one small keepalive writer (one `setInterval` per in-flight stream). Net new code is small; most of the fix is *not calling* the wrong function at the wrong time.

**Phone-OS direction:** more reliable cross-machine state reconciliation without polling is directly the kind of "proactive, reliable, works when a connection blips" behavior the phone-OS vision needs.

**User impact:** removes a false alarm that would otherwise cost the user a manual "Approve again" click and manual judgment about whether it's safe to do so — strictly more capable/less error-prone, not more passive.

## Existing-test conflict (must be resolved deliberately, not accidentally)

`dashboard/test/merge_failover.test.js:78-82` pins today's buggy behavior: *"a webhook that accepted the request and then went away is interrupted, not unreachable (it may be merging)"*. Its own comment ("it may be merging") already names the bug. This test must be rewritten, split into the still-running vs. genuinely-gone cases below — not left as a coincidental pass.

## Tests to write FIRST

**Server — `merge_progress.js` (keepalive + `/inflight` body):**
1. Streaming `approveResponder` writes a `{type:"ping"}` ndjson line every `PING_INTERVAL_MS`; client-visible, doesn't disturb progress/result parsing.
2. The ping interval is cleared when `result()` ends the response — no leaked timer, no write-after-end throw.
3. The ping interval is cleared when the socket is destroyed mid-stream — no unhandled write errors.
4. New pure helper `inflightBody(inflight, url)`: `{entry:null}` for an absent/empty/junk url, `{entry:{...}}` for a present one, `{entries:{...}}` for no url — never throws on a malformed/huge url string.

**Client — `approve_stream.js`:**
5. Stream destroyed, `/inflight` says absent → resolves `{merged:false, interrupted:true, reason:'...'}` (real two-route test server, not the old bespoke single-handler one).
6. Stream destroyed, `/inflight` says present → resolves `{merged:false, interrupted:false, stillRunning:true, reason:'Lost contact with the Mac mini; checking whether the merge is still running.'}`, and `onNotice` was called with that exact text.
7. **Attack: "/inflight itself unreachable"** — the probe errors/refuses → fails safe to `interrupted:true` (never hangs, never rejects the outer promise).
8. **Attack: "merge finishes while disconnected"** — the tracker's `end()` has already removed the inflight entry by the time the probe runs → resolves `interrupted:true` (documents that "merged-while-disconnected" correction is `mergeOps.githubChanged()`'s job, not this code's — no regression, no new work needed there).
9. Half-open socket, no close, no pings, silence past `stallMs` (fake timers) → reconciliation fires without waiting for a socket event.
10. Keepalive pings reset the stall watchdog — advancing fake time well past `stallMs` while pings keep arriving never triggers reconciliation.
11. **Attack: repeats/concurrency** — a stall-timeout and a real `close` event both fire close together → the promise still settles exactly once, no unhandled rejection.
12. **Attack: malformed input** — existing garbled/oversized-line test extended to assert garbage data still resets the stall watchdog (doesn't itself look like a stall).
13. Existing happy-path tests (success, refusal-in-result, reengaged, legacy plain-JSON webhook, junk URL, "listener throws") still pass unmodified — none of them ever reach the new reconciliation path.

**`merge_ops.js`:**
14. `notice()` now also refreshes `lastEventAt`, so a live "Lost contact…"/failover notice extends the 45-minute `maxMergingMs` grace window instead of competing with it; existing expiry test still passes for the no-notice case.

**`approve_flow.js`:**
15. `send()` resolving `{stillRunning:true, reason}` → `approve()` resolves that shape, does **not** call `ledger.conclude`, calls `mergeOps.notice(url, reason)`, and calls the new one-shot `catchUp(url)`.
16. `onNotice` is correctly threaded as `onSwitch` through `approveOnAnyMachine`'s `send` closure (not just testable in isolation — prove the wiring).
17. **Attack:** `catchUp` throwing/rejecting never loses the already-resolved click result.

**New `merge_catchup.js`** (extracted from `index.js`'s inline `catchUpMerges`, so AC2 is actually testable):
18. **AC2 regression test**: a PR with `mergeQueue.state === 'running'` and no local `mergeOps` entry (simulating an app restart) gets one `/merge-progress` fetch, is adopted into `mergeOps`, and is pushed — "the card shows Merging" without a stream.
19. A PR already `mergeOps`-state `'merging'` is skipped (no redundant fetch).
20. **Attack: repeats** — calling the catch-up twice while the first fetch is still in flight issues only one request (existing `catchingUp` guard, currently untested).
21. **Attack: dependency failing** — the progress fetch rejects/times out → swallowed, no throw.
22. **Attack: malformed** — a 200 response missing `.merge.progress` → no adoption, no crash.
23. `catchUpOne(url)` (the single-URL entry point `approve_flow`'s `stillRunning` branch calls) behaves the same as the list-path, standalone.

No Decisions section: the ticket is concrete and every choice above (ping/stall intervals, where the keepalive lives, how reconciliation plugs into existing state) is resolvable by reusing an existing, already-decided pattern — nothing here needs the owner's judgment call.

## Task List

1. `merge_progress.js`: add `PING_INTERVAL_MS`, keepalive writer in `approveResponder` (streaming only), cleared on end/close/error.
2. `merge_progress.js`: add `inflightBody(inflight, url)` pure helper next to `createInflightStore`.
3. `index.js`: add `GET /inflight` route using the existing `inflight` instance + `inflightBody`.
4. `merge_ops.js`: `notice()` refreshes `lastEventAt`.
5. New `electron/main/merge_catchup.js`: extract `catchUpMerges`/single-PR catch-up (`catchUpOne`) out of `index.js` into a testable factory (`mergeOps`, `fetchProgress`, `push` injected).
6. `index.js`: wire `catchUpMerges`/`catchUpOne` from the new module in place of the inline closure.
7. `approve_stream.js`: add `STALL_MS`, injectable `checkInflight`, `onNotice` option; replace the immediate `interrupted()` resolution with an async `reconcile()` that probes `/inflight` once and resolves either `interrupted:true` (absent) or `stillRunning:true` (present); add the stall watchdog reset on every received chunk.
8. `approve_flow.js`: thread `onNotice: onSwitch` into the `send` call to `approveOnAnyMachine`; accept a new `catchUp` param; in `answered()`, branch on `result?.stillRunning` before the `interrupted` branch — no ledger conclude, call `mergeOps.notice()` + `catchUp(url)`.
9. Write/port all 23 tests above across `merge_gate_progress.test.js` (or a new file for `inflightBody`), `approve_stream.test.js`, `merge_failover.test.js` (rewriting the pinned test at line 78), `merge_ops.test.js`, a new `merge_catchup.test.js`, and `approve_flow`'s existing test file.
10. Run the full dashboard test suite (`npm test` in `dashboard/`), not just the touched files, per the full-suite-before-merge rule.
11. Pin screenshots at 900px and 1440px of a card showing the transient "Lost contact…" notice (force it via the existing `MARVIN_MR_FIXTURE`/manual trigger) on the PR.