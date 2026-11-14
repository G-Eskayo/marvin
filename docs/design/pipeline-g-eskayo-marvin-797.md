## North-star fit

**Reuses:** `webhook-server/merge_facts.js`'s `createUnbuiltCache`/`createFixTicketsCache` shape (TTL + single-flight refresh, "keep the last answer on failure") for the new merge-server health probe; `electron/main/mr_review.js:listPipelinePrs`'s existing per-PR annotation fields (`sentBack`, `ticketClosed`, `conflicts` — "true means something's wrong") for the new `mergeServerDown` field; `src/lib/prState.js:describePrState`'s existing wrap-and-override pattern (it already wraps `describeState` once, for drafts) for the merge-server-down override; `src/lib/pr_fetch_status.js:prFetchBanner` + `src/components/MrReview.jsx:FetchBanner` (the exact "existing FetchBanner style" the ticket names) for the banner, by adding one more field it understands rather than a parallel banner mechanism; the already-wired `{ signal: AbortSignal.timeout(N) }` idiom used by `getRebaseStatus`/`getAutoMergeShadow`/`getMergeQueue` in `electron/main/index.js` for the new cheap probe's own timeout; the webhook server's existing flat `if (req.method === 'GET' && req.url === '/...')` route list (`webhook-server/index.js`) for the new `/health` route, mirroring `/sessions`/`/helpers` (unauthenticated, read-only, no side effects).

**Simplest sufficient approach:** one new small pure module (`merge_server_health.js`) with a TTL+single-flight cache around one new trivial server route, one new boolean field threaded through the one function the ticket's own evidence already points at (`listPipelinePrs`), and one new early-return each in `describeState` and `prFetchBanner` — no new test harness, no new UI component, no change to the real approve/deny/merge-failover machinery (marvin#762/#940), which already owns what happens when an *attempted* approve fails or the Mini comes and goes mid-merge.

**Token/compute cost:** saves — the fix removes up to three stacked 3–5s network timeouts from every list load when the Mini is down (the evidence's own complaint), replacing them with one ≤1.5s probe that's cached for ~30s, so repeat loads cost nothing extra.

**Phone-OS direction:** neutral/positive — a merge server that fails fast and says so in words is a precondition for any remote (phone) approval flow built on the same dashboard IPC later.

**User capability:** more capable, not more passive — it removes a silent wait-and-wrong-error trap (the user currently doesn't learn anything is wrong until two different vague errors show up); it doesn't take any decision away from the user, it just tells them sooner.

**Machine:** no machine-specific work; this is dashboard/webhook-server JS run on whichever Mac the dashboard is open on, probing whichever host `device_identity.js`'s `resolveServiceDefaults()` already resolves as the merge server.

One correction to the ticket's own framing: its evidence cites `dashboard/electron/main/index.js:115-119,585,844,881`, but those line numbers no longer line up with the sequential-await problem — the file has grown since the ticket was filed. The real sequential-await site is `electron/main/mr_review.js`'s `listPipelinePrs` (now around lines 304–362): `rebaseStatus()`, `autoMergeShadow()`, and `mergeQueue()` are each separately `await`ed, one after another, and each is backed by a 3–5s-timeout `fetch` to the Mini defined in `index.js` (`getRebaseStatus` ~1045, `getAutoMergeShadow` ~1008, `getMergeQueue` ~1067). That's the "three optional reads" the ticket's Fix section means.

## Tests (written first)

In `test/merge_server_health.js` tests (new file, mirrors `test/merge_queue.test.js`'s `createUnbuiltCache` tests):
1. A probe that resolves `true` → `check()` returns `true`, `peek()` reflects it.
2. A probe that resolves `false`, or **rejects/throws** → `check()` returns `false` (never throws) — "each dependency failing."
3. Within the TTL window, repeated `check()` calls do not call the probe again (cached), even if the probe's answer would now differ — "server flaps every 10s" doesn't flicker the banner faster than ~30s.
4. After the TTL elapses, the next `check()` re-probes and picks up a changed answer — cache isn't permanent.
5. Overlapping concurrent `check()` calls while a probe is in flight share one outstanding probe call (single-flight) — "repeats and concurrency."
6. A probe fn that never resolves within its own timeout still leaves `check()` resolving to `false` once that rejection lands (simulated via a controlled rejecting promise) — never hangs the caller.

In `test/mr_review.test.js` (extends the existing `describe('listPipelinePrs: post-merge rebase result (#225)')` block style):
7. `mergeServerUp` resolving `false` → `rebaseStatus`/`autoMergeShadow`/`mergeQueue` getters are **never called** (asserted via call-count spies), and each PR gets `mergeServerDown: true`.
8. `mergeServerUp` resolving `true` (default, for back-compat with every existing caller that omits it) → all three getters are called, and each PR gets `mergeServerDown: false` — existing rebase/shadow/queue-line behavior unchanged (regression guard on the parallelization).
9. The three getters run **in parallel**, not sequentially: each mock getter delays via its own timer (e.g. 50ms); assert total `listPipelinePrs()` time is close to the slowest one, not their sum — this is the concrete regression test for "run the three optional reads in parallel."
10. One of the three getters still rejects even while the server is "up" (a flap mid-call, or "server answers the probe but times out on approve"'s read-side analogue): that one PR field falls back to its existing empty/`null` default and the other two still populate — no dependency's failure blocks the others (already true today for each individually; the test pins it under the new parallel+gated code path).
11. `mergeServerUp` option omitted entirely → defaults to "up", identical to every existing call site in `index.js` and the existing tests that don't pass it.

In `test/pr_state.test.js` (extends the existing `describe('describePrState: ...')` blocks):
12. `pr.mergeServerDown: true` on an otherwise `ready` PR → `approve: 'disabled'`, headline says the Mini isn't answering, `deny` stays `'enabled'` (Deny is out of this ticket's scope — see Decisions-equivalent note below).
13. `pr.mergeServerDown: true` on a PR mid-merge (`status: 'approving'`/`'queued'`/`'waiting-memory'`/`'merged'`/`'interrupted'`) → unchanged; the real-time merge state wins, never overridden by the cached probe — "server answers the probe but times out on approve" must not make an in-flight merge look like it never started.
14. `pr.mergeServerDown: true` on a PR that's already blocked for an unrelated reason (`sentBack`, `ticketClosed`, `conflicts`, `needsImages`, decisions-pending/vague) → headline/detail stay the PR's own reason, not overwritten by the server-down message (Approve was already hidden/disabled there regardless).
15. `pr.mergeServerDown: true` + `pr.isDraft` → Approve still ends up `'hidden'` via the existing draft rule, not `'disabled'` — the two wrapper rules compose correctly.
16. `pr.mergeServerDown` omitted/`false` (every existing test in the file) → byte-identical behavior to today (regression guard).

In `test/github_feed.test.js` (extends the existing `prFetchBanner` tests):
17. `prFetchBanner({ mergeServerUp: false })` → `{ tone: 'amber', text: "The Mac mini isn't answering, so approvals will wait." }`, taking priority even when `errors`/`source` are also set (both problems real at once — show the more actionable one).
18. `prFetchBanner({ mergeServerUp: true, ...anything })` and `prFetchBanner({})` (field omitted) → identical to current behavior for every existing case in the file (regression guard on the default).

Webhook route (`webhook-server/index.js`): no new HTTP-level test — consistent with the file's existing convention (`/rebase-status`, `/merge-history`, etc. are one-line routes exercised only indirectly, never via a direct HTTP test harness); the route is a static `{"ok":true}` 200 with no I/O and nothing to break at the unit level beyond what's already covered by #7–11 (which mock its client side).

## Decisions

None. Scope stayed inside the ticket's own acceptance criteria: Approve is disabled and the banner shown; Deny is left as-is (it already hits the same webhook, and the ticket's Fix/acceptance text only names Approve — gating Deny too would be a reasonable follow-on, but it's not what was asked, and adding it risks repeating whatever caused the two prior automated attempts to fail code review with no detail left behind). The probe timeout (1.5s) and reuse of the existing `AbortSignal.timeout` idiom are implementation details, not choices that need the owner.

## Task List

1. `webhook-server/index.js`: add `if (req.method === 'GET' && req.url === '/health')` → `res.writeHead(200, {...}).end('{"ok":true}')`, placed beside the other read-only GET routes (`/sessions`, `/helpers`).
2. New `dashboard/electron/main/merge_server_health.js`: `createMergeServerHealth({ probe, ttlMs = 30_000, now = Date.now })` → `{ check(), peek(), lastCheckedAt() }`, TTL + single-flight, modeled on `merge_facts.js`'s `createUnbuiltCache`. Write tests 1–6 first, then implement.
3. `electron/main/index.js`: add `probeMergeServerHealth` (fetch `MR_WEBHOOK_URL.replace(/\/approve$/, '/health')` with `AbortSignal.timeout(1500)`, `catch`→`false`) and a module-level `mergeServerHealth = createMergeServerHealth({ probe: probeMergeServerHealth })` near the existing `MR_WEBHOOK_URL`/`getRebaseStatus` definitions.
4. `electron/main/mr_review.js`: add a `mergeServerUp` option (default `async () => true`) to `listPipelinePrs`; await it once; gate `rebaseStatus()`/`autoMergeShadow()`/`mergeQueue()` on it (skip entirely when down) and run them via `Promise.all` instead of sequential `await`s; add `mergeServerDown: !serverUp` to each returned PR. Write tests 7–11 first, then implement.
5. `electron/main/index.js`: pass `mergeServerUp: () => mergeServerHealth.check()` into both `listPipelinePrs` call sites (`pipelineCardFromMemory` and the `mrList` coalesce); after `mrList()` resolves inside the `mr:list` handler, set `prFetch = { ...prFetch, mergeServerUp: mergeServerHealth.peek() }` so `mr:listStatus` carries it without a second IPC round-trip.
6. `src/lib/prState.js`: rename the body of `describeState` to `describeStateCore`; `describeState` calls it, then if `pr.mergeServerDown && view.approve === 'enabled'`, returns `{ ...view, kind: 'merge-server-down', tone: 'wait', approve: 'disabled', headline: "Can't approve: the Mac mini isn't answering", detail: 'Approvals will wait until it answers again.' }`, else returns `view` unchanged. Write tests 12–16 first, then implement.
7. `src/lib/pr_fetch_status.js`: add `mergeServerUp = true` to `prFetchBanner`'s destructured param; if `mergeServerUp === false`, return `{ tone: 'amber', text: "The Mac mini isn't answering, so approvals will wait." }` before the existing `source`/`errors` checks. Write tests 17–18 first, then implement.
8. `src/components/MrReview.jsx`: thread the new `mergeServerUp` field from `fetchStatus` through to `<FetchBanner status={fetchStatus} />` — no component change needed since `fetchStatus` already flows straight from `window.api.mr.listStatus()` into `FetchBanner`; just confirm end-to-end once steps 1–7 land, and take the 900px/1440px screenshots the acceptance criteria ask for (Mini down: banner + disabled Approve; Mini back up: banner gone on the next probe) via `marvin-show`.