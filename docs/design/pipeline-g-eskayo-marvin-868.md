## North-star fit

**Reuses before adding anything new:** `checkRuns()` and `gateCheckNames()` (`dashboard/webhook-server/ci_status.js`) for parsing/naming GitHub's per-check rollup — `gateCheckNames()` is already proven (existing test, "no merge waits on GitHub") to return marvin's *full* required-checks list, so no new JSON-reading code is needed. `MergeFailure`/`refusal()` (`failure.js`) for the new outcomes, matching every other gate refusal. The bounded-poll *shape* of `mergeableNow()` (`merge.js`) — already allowlisted in `dashboard/test/polling_guard.test.js` for exactly this situation ("GitHub computes X lazily with no event; bounded N×M"). The existing pre-rebase CI_FAILED reengage block in `mergePrUnqueued` (`merge.js` ~L907-919) gets factored into one helper instead of being duplicated for the new post-push call site. The already-serialized `inRepoQueue` is what turns "bounded wait" into "never hangs the merge queue" — I don't need to build queue-awareness myself, just make sure the wait itself is bounded.

**Simplest sufficient approach:** a synchronous, bounded poll inside the gate's own call (not a new background watcher). `gh_watch.js`'s existing check-watch (`startCheckWatch`) is a *long-lived* ~20s background interval feeding UI cache invalidation and the pre-gate merge-queue retry — wiring a one-shot, already-time-boxed wait into that shared singleton would mean threading a subscription API through `deps` for no real benefit, and risks missing events for repos not already registered with it. A self-contained poll, in the same file as the rollup-parsing helpers it reuses, is the lower-risk, more reviewable choice — and matches the only existing precedent for "wait on GitHub's lazy computation."

**Resources:** one new ~30-line function, no new files, no new dependencies; ≤80 cheap `gh pr view` calls over the worst-case wait, only on merges that actually needed a rebase (today's failure mode: all of them, once branch protection is on).

**Phone-OS direction:** not applicable — internal pipeline plumbing.

**More capable or more passive:** removes a real failure mode that currently dead-ends a gated merge and needs Gil's manual retry; both new outcomes (CI_FAILED → rebuild, CI_TIMEOUT/CI_SUPERSEDED → "approve again," never silently) keep the actual judgment calls (is the code wrong? is it worth re-approving?) with Gil or the ticket pipeline, not hidden.

## Design

After `rebaseAndRetestFn` pushes the rebased commit and the gate's own tests have passed, add one step before `gh pr merge` is attempted: `waitForRequiredChecks(prUrl, exec, names, opts)` in `ci_status.js`, where `names = gateCheckNames(ctx ? ctx.clone : REPO_PATH)` (already computed today for `postGateStatus`).

It polls `gh pr view --json statusCheckRollup,headRefOid` (one call per tick):
- a fetch error or unparseable JSON → treated as "not yet reported" (keep polling — failing *open* here would let a GitHub blip through before its checks actually passed, the opposite of `assertChecksGreen`'s existing fail-open, which is safe only because that check runs *before* the gate's own local retest does the real work);
- any required name's row shows `status === 'failed'` → throw `MergeFailure(refusal('CI_FAILED', ...))` naming it, same contract `assertChecksGreen` already uses;
- the PR's `headRefOid` has changed since the first poll → throw `CI_SUPERSEDED` (escalate, not reengage: the branch moved again, not the code);
- every required name is `done` and none failed → return;
- elapsed ≥ `CHECKS_WAIT_TIMEOUT_MS` (20 min, new constant, same "stated time limit" convention as `GATE_TIMEOUT_MS`/`DISK_FIRST_AID_TIMEOUT_MS` — a technical tuning choice, not a Decision) → throw `CI_TIMEOUT` (escalate, not reengage, same posture as `GATE_INFRA`: the machine/GitHub side, not necessarily the PR).

In `mergePrUnqueued`, `waitForRequiredChecks` is injected via `deps` (so tests never touch a real clock), called with the existing `sleep` dep. `CI_FAILED` routes through a new shared `reengageCiFailed(...)` helper (factored out of the existing pre-gate block, used by both call sites). Everything else (`CI_TIMEOUT`, `CI_SUPERSEDED`, any other `MergeFailure`) is staged `'gate','failed'` and rethrown, unreengaged — the PR stays open, nothing is sent back for rework. `dashboard/src/lib/stage_strip.js`'s `REMEDIATION_BY_CODE` gets entries for both new codes so they render legibly instead of falling back to "Unclassified failure."

## Tests to write first

From "How we'll try to break it":
1. **Still queued** — required checks start `queued`/`running`; the wait keeps polling and resolves once all report success.
2. **A cancelled run (a newer push)** — `headRefOid` differs on a later poll than the first → `CI_SUPERSEDED`, escalate, not reengaged, loop stops immediately (doesn't run to the timeout).
3. **A required name CI never reports** — a required name never appears in the rollup at all → `CI_TIMEOUT` after the *injected* (tiny, real-time) limit elapses, naming which check(s) never answered. Timeout/poll intervals are injected parameters in every test (same style as `withGateTimeout`'s own tests, e.g. `ms: 10`) — **no real sleeps, no fake timers, nothing that can hang `npm test`** (the probable cause of two of the three prior failed attempts' 1200s timeouts).
4. **GitHub errors/rate limits while waiting** — `gh pr view` rejects on several consecutive polls, then succeeds with passing checks → wait survives the errors and still resolves (treated as "not yet reported," never as "done" or "failed").

Misuse the ticket's list didn't name:
5. A required check genuinely `FAILURE` → `CI_FAILED`, named, ticket reengaged with a comment naming the check (ticketNumber present); thrown un-reengaged when there's no linked ticket (mirrors the existing pre-gate CI_FAILED-with-no-ticket test).
6. Empty/missing required-checks list (`names = []`) → returns immediately, zero `gh` calls (bad/empty input, and a performance guard: no needless polling on a project with no required-checks.json).
7. Malformed `gh pr view` JSON (huge/garbled stdout) → treated as "not yet reported," never a crash.
8. **Integration, `mergePrUnqueued`:** the `gate: true` path now calls the wait before `gh pr merge`; the existing `gate: false` (no rebase needed) path is unchanged — the new wait is never invoked and no new `gh` calls appear (regression guard against widening scope).
9. **`polling_guard.test.js`:** add the `ALLOWLIST` entry for `webhook-server/ci_status.js` (`timeout-loop`, 1, citing marvin#868 and the `mergeableNow` precedent) and confirm its existing "every timer... is allowlisted with its count and a reason" test still passes against the real source — this is very likely what sank at least one prior attempt's code review, since a raw poll loop with no allowlist entry fails this test outright.

Not retested here (already covered elsewhere, out of scope): concurrent Approves on the same PR (`mergeLatch`/`mergeQueue.isRunning`), stale `needs-reengagement` mid-wait (`assertNotSentBack` already runs once before the gate starts, same as every other gate state today).

## Decisions

None. The timeout value, the escalate-not-reengage posture for `CI_TIMEOUT`/`CI_SUPERSEDED`, and the allowlist-over-rearchitecting-around-`gh_watch.js` call are all inferable from existing, already-reviewed conventions in this exact file (`GATE_INFRA`, `MEMORY_PRESSURE`, `mergeableNow`) — none of them is a fresh judgment call for Gil.

## Task List

1. `dashboard/webhook-server/ci_status.js`: add `waitForRequiredChecks(prUrl, exec, names, opts)` plus exported `CHECKS_WAIT_TIMEOUT_MS` / `CHECKS_POLL_MS`, reusing `checkRuns()`/`MergeFailure`/`refusal()`.
2. `dashboard/test/ci_status.test.js`: tests 1–7 above, all with injected tiny `timeoutMs`/`pollMs` and a trivial `sleep`.
3. `dashboard/test/polling_guard.test.js`: add the `ALLOWLIST` entry for `ci_status.js`; confirm the allowlist test passes.
4. `dashboard/webhook-server/merge.js`: factor the pre-gate CI_FAILED block into a shared `reengageCiFailed(...)` helper (no behavior change at that call site).
5. `dashboard/webhook-server/merge.js`: wire `waitForRequiredChecks` into `mergePrUnqueued`'s `if (gate)` branch (after `postGateStatus`), injectable via `deps`; route `CI_FAILED` through the shared helper, let other codes escalate unreengaged.
6. `dashboard/test/merge.test.js`: tests 5, 8 above.
7. `dashboard/src/lib/stage_strip.js`: add `CI_TIMEOUT`/`CI_SUPERSEDED` to `REMEDIATION_BY_CODE`.
8. Run the targeted suites (`ci_status`, `polling_guard`, `merge`) then the full `vitest run` + affected `pytest` before opening the PR.