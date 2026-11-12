## North-star fit

**Reuses before adding anything new:**
- `mergeOps.notice(url, text)` and `mergeOps.adopt(url, progress)` (`dashboard/electron/main/merge_ops.js`) — the exact primitives `merge_failover.js` already uses for "the Mac mini is offline, merging on this MacBook Pro instead." The renderer already shows `m.notice` while `state === 'merging'` (`MrReview.jsx:214`, `statusFromOp`), so the new "Lost contact… checking" message needs **zero new UI code**.
- `GET /merge-progress` (`webhook-server/index.js:229`, backed by `createLiveMerges` in `merge_stage_relay.js`) stays the one place full stage detail is read from — the new endpoint only answers "is this URL still in flight," it doesn't duplicate progress reporting.
- `createInflightStore`/`inflightPath` (`webhook-server/merge_progress.js:17-61`) — `GET /inflight` is a thin **non-destructive** read next to the existing destructive `takeInterruptedMerges`, not a new storage mechanism.
- The `endpoint(machine, name)` URL-building pattern and `machines()`/`machine` resolution already in `electron/main/merge_failover.js` for reaching the right webhook.
- Existing DI/test conventions: real local HTTP servers (`approve_stream.test.js`'s `serve()`), injectable `now`/timeouts (`CONNECT_TIMEOUT_MS` pattern) — no mocking of the collaborator's protocol.

**Why simplest sufficient:** the only genuinely new runtime behavior is "don't trust a dropped connection as proof the merge died — ask once before downgrading the card." That's a small, bounded, pollable state check reusing two read-only endpoints (one of which already exists), not a new reconnect/resume protocol or websocket.

**Token/resource cost:** one new 10s server-side ping line while a stream is open (bounded, only while actively following a merge) and a handful of extra GETs only *on* a drop or *on* mount — not a steady-state poll loop. Cheap, incident-triggered.

**Phone-OS direction:** this exact failure mode — a stream dying on sleep/backgrounding/network handoff — is the normal case for a mobile client, not an edge case. Making the dashboard resilient to it now is direct groundwork for MARVIN Mobile's dashboard surface.

**More capable, not more passive:** pure reliability fix — removes a trap where the owner's only visible option ("Approve again") risks a duplicate merge, and removes a card stuck on "Merging…" for 45 minutes with no real signal. Doesn't change what the owner does himself.

I checked this against the two in-code comments the ticket's evidence cites (`approve_stream.js:12-14`, `merge_ops.js:5`) — both currently **conflate** "stream dropped" with "webhook restarted." That conflation is the actual root cause, confirmed by reading the code, not just the ticket's framing.

No Decisions section: the remaining open parameters (poll interval, retry backoff, give-up window for the reality check) are tuning constants, not product choices — `mergeOps`'s existing 45-minute `maxMergingMs` safety net already covers "merge genuinely taking too long," so the new logic only needs a short bounded retry for "can I reach /inflight right now."

## Tests first

**From "How we'll try to break it":**
1. Stream drops mid-merge, but `/inflight` still lists the URL → card shows "Lost contact… checking," then keeps following via polled `/merge-progress`, and ends on the real `merged: true` result (not "interrupted").
2. **Merge finishes while disconnected**: by the time the first `/inflight` check runs, the entry's already been removed (tracker's `end()` ran), but `/merge-progress` still shows the finished `outcome` (kept for "a late reader," `merge_stage_relay.js:59`) → resolves immediately with the real outcome, never polls forever, never shows a false interruption.
3. **`/inflight` itself unreachable** (refused/timeout on every retry) → bounded retries, then falls back to the existing "interrupted, Approve again" message — never hangs, never crashes.

**Additional misuse the section missed:**
4. `/inflight` reachable but empty for that URL, **and** `/merge-progress` also has no entry → falls back to interrupted immediately, no needless wait (truly-gone case).
5. A person clicks Approve again *while* the reconnect-and-follow is in progress → `mergeQueue.isRunning`/`ALREADY_MERGING` (409) and `mergeOps.start()`'s already-merging guard still block a second merge — verifies the fix doesn't reopen the exact duplicate-merge hole the ticket reports.
6. Malformed/garbled bodies from `/inflight` or `/merge-progress` (not JSON, wrong shape, `merge` holding a string) are treated as "can't confirm," never misread as "still running," never crash the poller.
7. `GET /inflight` itself: missing/corrupt `merge-inflight.json` (empty file, truncated JSON, an array instead of an object) → returns `{}`/`null`, doesn't throw, and — unlike `takeInterruptedMerges` — never clears or mutates the file.
8. `GET /inflight` with no `?url=`, with `?url=` for an absent PR, with a huge/duplicated/malformed query string, and with the wrong HTTP method (`POST /inflight` → 404) — same hardening as the existing `/merge-progress` route.
9. Concurrency: two different PRs drop their streams at once; each follows/resolves independently (keyed by URL in `mergeOps`), no cross-talk.
10. Stream keepalive: a silent socket (no bytes, not even a ping) is detected and treated as dropped within the injected dead-socket threshold (tested with a tiny injected value, not real 30s) — this is the direct fix for "Merging… for 45 min." A socket that keeps receiving `{type:"ping"}` lines is *not* prematurely killed, and ping lines never leak into `onEvent` or corrupt line-buffering of real events around them (oversized-line and garbled-line handling from the existing suite must still pass unchanged).
11. On-mount catch-up (AC2): a PR whose URL appears in `/inflight` but isn't yet known locally as `'merging'` (simulating an app restart that wiped `mergeOps`) gets adopted via `/merge-progress` and pushed to the card; a PR already known locally as `'merging'` is **not** re-fetched (no duplicate network calls); `/inflight` unreachable or empty at mount time leaves cards exactly as they were (fails open, one request per mount/refresh, reusing the existing `catchingUp` single-flight guard); a URL in `/inflight` that isn't in the currently-open list is ignored.
12. Regression guard: every existing case in `approve_stream.test.js` (explicit destroy, refusal, success, garbled/oversized lines, unreachable-at-connect, plain-JSON fallback) and `merge_ops.test.js`/`merge_failover.test.js`/`merge_stage_relay.test.js` keeps passing unmodified — the behavior change belongs in `approve_flow.js`/the new reconnect module, not in `approveMrStream`'s own resolution contract (aside from the additive ping-line/timeout handling) or in `mergeOps`'s semantics.

Tested against the real collaborator: the webhook-route tests spin up a real local HTTP server speaking the actual protocol (same style as `approve_stream.test.js`'s `serve()`), not a mock of `/inflight`/`/merge-progress`.

## Task List

1. `webhook-server/merge_progress.js`: add `peekInflight(file = inflightPath())` — non-destructive read of the inflight map (reuses `readJson`); export it.
2. `webhook-server/merge_progress.js`: add a keepalive to `approveResponder` — `STREAM_PING_MS` (default 10s, injectable `pingMs` option), writing `{type:"ping"}\n` on an interval while `streaming`, cleared on `result()` and on `res.on('close', ...)`.
3. `webhook-server/index.js`: add `GET /inflight` (optionally `?url=`) wired to `peekInflight()`, same shape/style as the existing `/merge-progress` route; pass `pingMs` through to `approveResponder` at the `/approve` call site.
4. `electron/main/approve_stream.js`: ignore `{type:"ping"}` lines in the NDJSON `line()` parser; add `STREAM_DEAD_MS` (default 30s, injectable `deadMs`) as a socket idle timeout on the streaming response, destroying the socket (routing into the existing `ended()`/`interrupted()` path) when no bytes — including pings — arrive in time.
5. New module `electron/main/merge_reconnect.js`: `checkInflight`/`checkProgress` (thin fetch wrappers against a machine's `/inflight` and `/merge-progress`) and `followAfterDrop({ url, machine, mergeOps, push, pollMs, maxRetries, sleep, fetchJson })` implementing the reality-check-then-follow-or-fall-back logic described above, with injectable timing for tests.
6. `electron/main/approve_flow.js`: in `answered()`, when `result?.interrupted`, push `mergeOps.notice(url, 'Lost contact with <machine>; checking whether the merge is still running')` and call `followAfterDrop(...)` instead of concluding `'interrupted'` immediately; factor the existing merged/reengaged tail (ledger conclude + `after()`) into a shared helper so both the normal result and the recovered-after-reconnect result flow through it identically.
7. `electron/main/index.js`: change `catchUpMerges`'s discovery source — fetch `/inflight` once per build/refresh, and for any listed URL not already known locally as `'merging'`, adopt via the existing `/merge-progress` call (keep the single-flight `catchingUp` guard); drop the dependency on `/merge-queue`'s `state === 'running'` flag as the sole trigger.
8. Write/extend tests per the list above: `webhook-server` route + `peekInflight` tests, `approve_stream.test.js` additions (ping passthrough, dead-socket timeout), new `merge_reconnect.test.js`, `approve_flow` integration tests for the interrupted→follow path, and `index.js`'s `catchUpMerges` tests for the mount case.
9. Capture before/after screenshots of the card showing the new "Lost contact… checking" notice at 900px and 1440px (reusing the existing sandboxed-app evidence-capture pattern, e.g. `MARVIN_MR_FIXTURE`/`merge_motion_evidence.mjs`'s approach), pin them to the PR's commit SHA per `ui_evidence.js`'s rules.
10. Run the full dashboard test suite plus the Python/lib suites before opening the PR, per the full-suites-before-hand-merge rule.