# Plan: G-Eskayo/marvin#797 — say when the Mac mini merge server isn't answering

## North-star fit

Reuses, before adding anything:
- **`dashboard/electron/main/rework.js`'s `getReworkStatus`/`clearReworkCache`** shape (module-level `{at, value}` cache, TTL constant, `clear...Cache` export) — model for the new health-probe cache. Same shape already used by `queue.js`, `devices.js`, `usage_report.js`.
- **`webhook-server/index.js`'s existing `if (req.method === 'GET' && req.url === '/rebase-status') {...}` dispatch idiom** — model for the new `/health` route; no new routing mechanism.
- **`mr_review.js`'s `listPipelinePrs`'s existing "best-effort, catch-and-default" pattern** (`sentBackTickets`/`closedTickets`/`autoMergeShadow`: a failing lookup never hides a PR, just flags nothing) — the three merge-server reads keep that same contract, just run concurrently and get skipped outright when the probe says down.
- **`src/lib/pr_fetch_status.js`'s `prFetchBanner()` precedence chain** (already has a `source.from === 'mini'` branch) — one more branch, zero changes to the `FetchBanner` component itself.
- **`src/lib/prState.js`'s `describeState()` ranked-conditions ladder** (`base()` helper) — one new branch in the same shape as `sentBack`/`ticketClosed`/etc. No new UI component, no new prop threading: the fact rides on the `pr` object exactly like `rebase`/`autoMerge`/`mergeQueue` already do.

No new polling, no new global store, no second cache mechanism. The only genuinely new code is a ~10-line HTTP route and a ~30-line TTL-cache module mirroring `rework.js`.

**Where it saves:** removes up to ~6s of blocking wait (2 of 3 sequential 3s timeouts) from every cold list load once the Mini is confirmed down, by skipping those reads entirely instead of hitting dead sockets one at a time.

**Where it spends:** one new cheap GET per 30s-window per machine talking to the Mini — negligible (no disk/gh read on the server side).

**Phone-OS direction:** keeps the merge server host-agnostic (driven by `MR_WEBHOOK_URL`/`resolveServiceDefaults()`, unchanged) — doesn't hardcode "the Mini" anywhere new.

**More capable, not more passive:** this is reliability/legibility work — replaces a misleading raw error (`EHOSTUNREACH`, `fetch failed`) and a slow dead-end click with an honest, fast status. No judgment is taken away from the owner.

## A real design fork — Decisions section needed

Investigating `merge_failover.js` (marvin#762) shows Approve **already has automatic machine failover**: `mergeMachines()` always ends the candidate list with "this machine's own webhook" (and CONTEXT.md confirms both the Mini and the MacBook each run their own `webhook-server`). So when the dashboard runs on the MacBook and the Mini is down, clicking Approve today generally still succeeds — it fails over silently to the MacBook's own merge service. Disabling Approve outright on a down-Mini probe (the ticket's literal wording) would block a path that currently works.

**Deny has no such failover** (`denyMr` in `mr_review.js:460` posts straight to `MR_DENY_WEBHOOK_URL`, no timeout, no fallback) — disabling Deny when the Mini is down is unambiguously correct and fixes the "fetch failed" symptom with no downside.

```markdown
<!-- marvin:decisions -->
### approve_disable_scope: When the Mac mini's health probe fails, should Approve be disabled too?
- [ ] A: Yes, always — disable Approve (and Deny) the moment the primary probe fails. Simplest, matches the ticket's literal wording; on a two-Mac setup this is occasionally stricter than necessary, since the local webhook on this machine could still complete the merge (marvin#762).
- [ ] B: Only when there's nowhere to fail over to — also do a fast local probe of this machine's own webhook before disabling Approve; disable only if both are unreachable. Deny is disabled either way (no failover). Slightly more code, preserves marvin#762's resilience guarantee.
```

The task list below implements the shared groundwork (probe, cache, banner, parallel reads, Deny fix) either way, and marks the one step that forks on this answer.

## Tests to write first

Mapped to the ticket's "How we'll try to break it" plus the standard misuse sweep (CONTEXT/ADR: outward-facing attack coverage doesn't apply — this is an internal Tailscale-only call with no external input surface).

**`dashboard/test/merge_server_health.test.js`** (new — the probe/cache module):
1. Probe returns `down: true` when `fetch` rejects with `AbortError` (timeout) — never throws out of the probe.
2. Probe returns `down: true` on `ECONNREFUSED`/`ENOTFOUND`/`EHOSTUNREACH`-style rejections.
3. Probe returns `down: true` when the response resolves but `res.ok` is `false` (e.g. 500) — status-only check, no body parsing (no JSON-malformed-body surface at all).
4. Probe returns `down: false` on a 200, ignoring an oversized/garbage body (confirms no JSON parsing happens).
5. **Flapping (ticket's break-it case):** two calls inside the TTL window return the same cached value and only one outbound `fetch` happens, even if a second real probe underneath would answer differently — proves the cache, not live state, drives the UI within the window.
6. **Repeats/concurrency:** two concurrent calls while a probe is in-flight share one promise — exactly one `fetch` call.
7. After the TTL expires, a new probe reflects the current (possibly flipped) state — not stuck on a stale value forever.
8. `clearMergeServerHealthCache()` forces the next call to re-probe.

**`dashboard/test/mr_review.test.js`** (extend):
9. The three merge-server reads (`rebaseStatus`, `autoMergeShadow`, `mergeQueue`) run concurrently, not sequentially — a test with instrumented resolvers (each records call-order/start-time) proves no read starts only after another finishes.
10. When `mergeServerHealth` reports down, none of `rebaseStatus`/`autoMergeShadow`/`mergeQueue` is called at all, and every PR gets `rebase: null`, `autoMerge: null`, `mergeQueue: null`, `mergeServerDown: true`.
11. When `mergeServerHealth` reports up, existing per-read failure handling is unchanged (re-run the existing "webhook down" rebase test at `mr_review.test.js:505` to confirm it still defaults to `null` rather than being swallowed by the new gating).
12. A failing `mergeServerHealth()` call itself (throws) defaults to "assume up" (consistent with every other best-effort lookup in this file) — never hides a PR or crashes the list.
13. `mergeServerHealth` omitted entirely (existing call sites that don't pass it, e.g. `mr:historyDetail`/`mr:reviewStatus`) behaves exactly as before — `mergeServerDown` is absent/falsy, zero regression.

**`dashboard/test/pr_fetch_status.test.js`** (new file — no dedicated file exists yet for this pure module):
14. `prFetchBanner({ mergeServer: { down: true } })` returns the amber "The Mac mini isn't answering, so approvals will wait." banner.
15. `prFetchBanner({ mergeServer: { down: false } })` (and `mergeServer: null`) returns the same result as before the change (no regression for the GitHub-errors and mini-feed-staleness branches already covered in `error_log.test.jsx`/`github_feed.test.js`).
16. Precedence: GitHub-unreachable errors still take the banner over merge-server-down when both are true (list reliability is the more urgent fact).

**`dashboard/test/pr_state.test.js`** (extend):
17. `pr.mergeServerDown: true` with no other blocker → Approve `disabled` (and Deny per the Decision above), with the fixed headline/detail text.
18. **Ticket's break-it case 1 — "answers the probe but times out on approve":** `pr.mergeServerDown` falsy (probe said up) but `status: 'error'`/`'interrupted'`/`'queued'` (the click itself failed) → existing branches win unchanged; confirms the new branch doesn't need to and doesn't interfere with the real-time error path.
19. `pr.mergeServerDown: true` together with `status: 'approving'`/`'queued'`/`'merged'` → the local click-state branches (ranked above the new one) still win; a stale "down" cached value never interrupts a merge already in flight.
20. `pr.mergeServerDown: true` together with a genuine content blocker (`pr.sentBack`, `pr.needsImages`, `pr.vague`, conflicts, failing checks) → the existing, more specific branch wins; connectivity never masks a real content reason.
21. `pr.canMerge === false` (pull-only node) with `pr.mergeServerDown: true` → still renders "Review on GitHub ↗", not the new branch (the early return in `ApproveDenyActions` already isolates this; regression guard).

**`dashboard/test/mr_review.test.jsx`** or **`MrReview`-adjacent component test** (wherever `prs.length === 0` empty-state logic is covered, or a new small test if none exists):
22. Zero open PRs but `fetchStatus.mergeServer.down === true` → shows the banner, not `EmptyState` (mirrors the existing `source.state !== 'fresh'` guard at `MrReview.jsx:808`).

No test is added for the raw `/health` route in `webhook-server/index.js` — consistent with this codebase's existing convention that the dispatcher's inline routes (`/rebase-status`, `/auto-merge-shadow`, `/merge-queue`) aren't HTTP-tested directly; the interesting behavior lives in the client-side probe, which is fully covered above.

## Task List

1. **`dashboard/webhook-server/index.js`** — add `GET /health` as the first route after the existing `timeRequest`/`copyRoute` calls: responds `200 {"ok":true}` immediately, no disk/gh/other calls.
2. **`dashboard/electron/main/merge_server_health.js`** (new) — `probeMergeServerHealth(url, {fetchImpl, timeoutMs})` (status-only check, `AbortSignal.timeout`, never throws) and `getMergeServerHealth({url, now, fetchImpl, ttlMs})` / `clearMergeServerHealthCache()`, following `rework.js`'s cache shape (30s TTL, single-flight `inflight`). Export the shared banner/card copy string here (one source of truth for "The Mac mini isn't answering…").
3. **`dashboard/electron/main/mr_review.js`** — refactor `listPipelinePrs`: accept a new `mergeServerHealth = null` option; when provided, call it once near the top (catch → default "up"); when it reports down, skip `rebaseStatus`/`autoMergeShadow`/`mergeQueue` entirely; otherwise run those three (plus `sentBackTickets`/`closedTickets`, which are GitHub-side and unrelated) via `Promise.all`, each still individually caught/defaulted as today. Attach `mergeServerDown: !!serverHealth.down` to every returned PR object.
4. **`dashboard/electron/main/index.js`** — define `getMergeServerHealth` next to `getRebaseStatus`/`getAutoMergeShadow`/`getMergeQueue` (same `MR_WEBHOOK_URL.replace(/\/approve$/, '/health')` pattern); pass it into both `listPipelinePrs` call sites (`mrList` coalesce and `pipelineCardFromMemory`); extend the `mr:listStatus` handler's returned object with `mergeServer: await getMergeServerHealth()` (cache read, no extra network cost).
5. **If Decision = B:** add a second, local-webhook probe (reusing the same `probeMergeServerHealth` against `localUrl`) and only set `mergeServerDown` when both the primary and local probes are down. **If Decision = A:** skip this step — step 3's single probe is sufficient.
6. **`dashboard/electron/main/index.js` — Deny path:** wrap/guard the `mr:deny` handler (or `denyMr` call) so a down primary short-circuits with the same friendly reason instead of letting the unbounded `fetch` hang/throw raw "fetch failed" (independent of the Decision above, since Deny has no failover in either option).
7. **`dashboard/src/lib/pr_fetch_status.js`** — add the merge-server-down branch to `prFetchBanner()`, ranked after GitHub-errors/mini-feed-staleness, reusing the shared copy string from step 2.
8. **`dashboard/src/lib/prState.js`** — add the `mergeServerDown` branch to `describeState()`, ranked after every content-blocking branch (sentBack, ticketClosed, conflicts, checks-failed, needsImages, vague/decisions-pending, baseProblem) and after the local click-state branches (approving/queued/waiting-memory/merged/interrupted), before the `ci.state === 'pending'`/`ready` fallback. Disables Approve (and Deny, consistent with step 6).
9. **`dashboard/src/components/MrReview.jsx`** — extend the `prs.length === 0` empty-state condition (line ~808) to also show the banner when `fetchStatus?.mergeServer?.down`.
10. Write/extend the tests listed above, confirming each fails against the pre-change code and passes after.
11. Run the dashboard's full test suite (not just the touched files — per the merge-gate's own rule, a hand-run of a subset isn't the gate).
12. Capture screenshots at 900px and 1440px of the down-Mini banner + disabled Approve/Deny state (using the existing `MARVIN_MR_FIXTURE` fixture mechanism to force a card into this state, same technique already used for other hard-to-reach card states), pin them on the PR per the acceptance criteria.
13. Open the PR with the Decision above carried as its Decisions section (buttons, not prose), naming #797.