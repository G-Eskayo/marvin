## North-star fit

**Reuses**, before adding anything: `assertChecksGreen`/`ciState`/`gateCheckNames` and the whole `postGateStatus` pattern in `dashboard/webhook-server/ci_status.js`; the poll-with-injectable-`sleep` shape of `mergeableNow` (`merge.js:800-813`); `classifyFailure`/`refusal`/`MergeFailure` from `failure.js` (no new error-text patterns); the existing merge-queue hold/retry machinery (`merge_queue.js:151-262`) that already requeues any non-fatal refusal, so a new `action:'retry'` code needs no new queue wiring; and the `rebaseAndRetestFn`/`deps` injection convention already used for `uiEvidence`, `decisions`, etc., for testability.

**Why this shape:** `lib/branch_protection.py`'s `settings()` makes GitHub require *every* name in `.github/required-checks.json`, regardless of `where`. That's a different question from what #1099/#1102 answered ("does the local gate need GitHub's copy to decide whether the code is good?" — no) — this is "will GitHub's merge API let the commit through?", which it won't until its own copies of those checks report success on that *exact* SHA. So the simplest sufficient fix is one new wait, scoped to the one place a brand-new, unchecked SHA gets created: right after the gate's own rebase pushes a commit, before calling `gh pr merge`. No new infra, no touching #1099/#1102's "gate is the check" logic (that stays correct for what it answers).

**Where it spends/saves:** it deliberately *spends* wall-clock time (not spent today) waiting out GitHub's own CI on the rebased commit — that's the ticket's whole point, trading a few extra minutes per rebased merge for not having every such merge dead-end at the last step once protection is on. It *saves* GitHub API calls by fetching the post-push SHA once and handing it to both `postGateStatus` and the new wait, instead of two separate `gh pr view` calls.

**Scope boundary (my call, not a Decision):** AC1 says "a gated merge **with a rebase**" — I'm scoping the new wait strictly to the `if (gate)` branch of `mergePrUnqueued` (`merge.js:929-1014`), not the no-rebase path. A no-rebase merge reuses a commit whose CI started when the PR was last pushed, long before Approve; the realistic race window is tiny and the ticket doesn't claim it's broken. Flagging this plainly rather than silently expanding scope.

**More capable, not more passive:** this removes a failure mode a human would otherwise have to notice and re-approve by hand once protection flips on (the issue's own motivation); a timeout/failure still surfaces by name, never hangs silently.

## Tests first (dashboard/test/ci_status.test.js unless noted)

New `describe('waitForRequiredChecks')` block, using injected `sleep`/`now` so nothing takes wall-clock time:

1. All required names already `SUCCESS` on the awaited SHA → resolves on the first poll, no `sleep` call.
2. A required check still `QUEUED`/`IN_PROGRESS` → polls again, then resolves once a later poll shows it `SUCCESS`.
3. A required name **absent** from the rollup entirely (workflow not scheduled yet) → treated as still-pending, not failing; resolves once it later appears green. *(AC3 / "queued")*
4. A required check reports `FAILURE` on the awaited SHA → throws `MergeFailure` `CI_FAILED` naming it, `action:'reengage'` (mirrors the existing `assertChecksGreen` CI_FAILED test shape). *(AC2)*
5. A required check reports `CANCELLED` on the awaited SHA while `headRefOid` is **unchanged** (a real cancellation, not a newer push) → also `CI_FAILED` naming it (reuses `ciState`'s existing `FAILED` set — no new logic needed).
6. The PR's `headRefOid` changes mid-wait (a newer push superseded our rebase, which is what actually cancels GitHub's run via `ci.yml`'s `concurrency.cancel-in-progress`) → throws a new `HEAD_MOVED`, `action:'retry'`, **never** reengage, and ignores whatever the (now-irrelevant) rollup for the new head says. *("a cancelled run (a newer push)")*
7. `gh` throws transient errors (`ECONNRESET`, "secondary rate limit") on several consecutive polls → keeps waiting (routes the error through `classifyFailure`; `retryable` or `UNKNOWN` never aborts early) and still resolves once the errors stop, within the timeout. *("GitHub returning errors or rate limits")*
8. `gh` throws a **non-retryable, named** error ("Bad credentials" / `GH_AUTH_INVALID`, or a missing-`gh` `TOOL_MISSING`) → fails fast with that code, not after burning the whole timeout window — proves permanent vs. transient errors are told apart via the existing classifier.
9. A required check that stays pending/missing for the entire window → throws `CI_TIMEOUT` naming the still-outstanding check(s), firing at (not before/long after) the configured deadline. *(AC3)*
10. Unreadable/empty `required-checks.json` (reuse the `dirWith(null/'{not json'/...)` fixture already in this file) → falls back to waiting on whatever GitHub actually reports for the SHA, verified against a rollup that is genuinely still failing (never a silent false pass).
11. Empty rollup at all (nothing reported yet right after push) with known required names → treated as "all missing", keeps waiting, doesn't falsely resolve as "none = passing" (that reading is correct for `ciState` used standalone, but wrong here where we *know* names are required).
12. Malformed `gh pr view` stdout (not JSON, or missing `headRefOid`/`statusCheckRollup`) → treated as a metadata hiccup, keeps polling, never throws/crashes (mirrors `assertChecksGreen`'s existing "does not block on a metadata hiccup" test).
13. Poll cadence: `sleep` is called with the configured interval between polls (guards against a retry storm hammering GitHub's API).

`gateCheckNames`/`requiredCheckNames` tests (same file, same `dirWith` fixture pattern):

14. `requiredCheckNames(dir)` returns **every** `checks[].name`, including `where:'ci'` ones (unlike `gateCheckNames`, which filters those out) — parity with `lib/required_checks.py:names()`, since that's what `branch_protection.py` feeds to GitHub.
15. Missing/broken list → `[]` (same resilience contract as `gateCheckNames`).

`merge.test.js` integration tests (extend `describe('merging waits for the repo's own CI')` or a sibling block, with `gate: true` + `rebaseAndRetestFn` → `{ok:true}`):

16. A required GitHub check fails on the rebased commit → `mergePrUnqueued` returns `{merged:false, reengaged:true, code:'CI_FAILED'}`; `gh pr merge` is **never** called.
17. A required check is pending then turns green on a later poll → merges, and `gh pr merge` is called only **after** the wait resolves (assert call order).
18. A required check never finishes → the promise **throws** `CI_TIMEOUT` (not reengaged — matches the `MERGE_REFUSED`/`BASE_MOVED` precedent at `merge.js:1041-1047`); `gh pr merge` never called.
19. `gate: false` (no rebase) → the new wait is **not** invoked at all (asserted via a spy on the injected `waitForChecksFn`), confirming the scope boundary above.
20. The SHA used for `postGateStatus` and for the new wait is fetched exactly once (`gh pr view ... --json headRefOid` called once per gate pass, not twice) — a resource-use regression guard.
21. Update the ~5 existing `gate:true` tests (lines ~190-260, 883-910) whose generic `exec` stub currently returns `{stdout:'',stderr:''}` for every call: extend the shared `execWithCodeReviewDefaults` helper (`merge.test.js:65-80`) to also answer the new `gh pr view ...headRefOid,statusCheckRollup` call with a default passing/empty rollup + stable SHA, so these keep testing their original concern instead of hanging on the new poll loop.

## Task List

1. `ci_status.js`: extend `ciState(rollup, { ignore, only })` to support an `only` allow-list (a name not in `only` is treated as not present), additive and backward-compatible.
2. `ci_status.js`: add `requiredCheckNames(dir)`, a sibling of `gateCheckNames` that returns **every** `checks[].name` (no `where` filter).
3. `ci_status.js`: factor the SHA-fetch out of `postGateStatus` into a small exported `currentHeadSha(prUrl, exec)`; give `postGateStatus` an optional `sha` param that skips its own fetch when provided (backward compatible — existing callers/tests with 3 args unchanged).
4. `ci_status.js`: add `REQUIRED_CHECKS_TIMEOUT_MS` (70 min — just past the ~65 min worst case documented in PR #1100) and `REQUIRED_CHECKS_POLL_MS` (15 s) constants, and `waitForRequiredChecks(prUrl, exec, { sha, names, timeoutMs, pollMs, sleep, now })`: polls `gh pr view --json headRefOid,statusCheckRollup`; short-circuits on head-move (`HEAD_MOVED`, retry) or a non-retryable classified error (via `classifyFailure`); uses `ciState(rollup, { only: names })` plus per-name presence tracking to tell "failing" / "still missing or pending" apart; throws `CI_FAILED` (reengage) or `CI_TIMEOUT` (retry) by the deadline; otherwise resolves.
5. Write the `ci_status.test.js` tests (items 1–15 above) against steps 1–4, before wiring them into `merge.js`.
6. `merge.js`: import `waitForRequiredChecks`, `requiredCheckNames`, `currentHeadSha`, `REQUIRED_CHECKS_TIMEOUT_MS`; add `checksTimeoutMs` and `waitForChecksFn = waitForRequiredChecks` as injectable `deps`/params, following the existing `rebaseAndRetestFn`/`gateTimeoutMs` convention.
7. `merge.js` (`mergePrUnqueued`, inside `if (gate) {...}`, right after the existing `stage('gate','passed'...)` logic at lines 1003-1012): fetch `sha` once via `currentHeadSha`; pass it to `postGateStatus`; call `waitForChecksFn` with `{ sha, names: requiredCheckNames(ctx ? ctx.clone : REPO_PATH), timeoutMs: checksTimeoutMs, sleep }`, catching `CI_FAILED` the same way the existing block at lines 910-919 does (`stage`, `recordFailureFn`, `reengage`, early return) and letting `CI_TIMEOUT`/`HEAD_MOVED` rethrow as a plain `MergeFailure` after `stage('gate','failed', ...)`, matching the `MERGE_REFUSED` precedent.
8. Update the ~5 existing `gate:true` tests per test item 21, and add the new `merge.test.js` integration tests (items 16-20).
9. Run the full dashboard suite (`npx vitest run` in `dashboard/`) and the drift check (`venv/bin/python lib/required_checks.py drift`) to confirm nothing else assumed the old (no-wait) behavior.
10. Update this ticket and its comment thread with what changed and the test count, same as sibling merge-gate PRs (#1100, #1102) — no code-level docs/ADR needed since `.github/required-checks.json`'s own `_readme` and `lib/required_checks.py`'s docstring already describe what branch protection requires; nothing here changes that contract.