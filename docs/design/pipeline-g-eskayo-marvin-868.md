## North-star fit

**Reuses, before adding anything new:**
- `mergeableNow` (`dashboard/webhook-server/merge.js`) — the existing "poll `gh pr view`, sleep, give up after N tries" shape for waiting out a GitHub-side recomputation. The new wait copies this shape (poll → sleep → deadline) rather than inventing a second polling idiom.
- `ciState` (`dashboard/webhook-server/ci_status.js`) — already turns a `statusCheckRollup` into `{state, failing, pending}`; the new `requiredCheckState` feeds it a filtered rollup instead of re-deriving pass/fail/pending logic.
- `gateCheckNames` (`dashboard/webhook-server/ci_status.js`) — same file, same shape, but for the **wrong** set here (it's the "ignore" list the gate already covers). `required_checks.py:names()` (`lib/required_checks.py`) is the Python-side function with the *right* semantics ("what branch protection requires" — every name, `where: both` and `where: ci`). The plan adds a JS mirror, `requiredCheckNames`, by refactoring `gateCheckNames`'s existing file-read into a shared `readChecks(dir)` helper both call — not a second independent parser.
- `refusal()` / `MergeFailure` (`failure.js`) and the existing `CI_FAILED` catch block in `mergePrUnqueued` (merge.js, the pre-gate `assertChecksGreen` handling) — the new post-rebase failure path reuses the identical code/action/stage/reengage shape instead of inventing new failure plumbing.
- `HOLD_UNTIL` (`merge_order.js`) and `REMEDIATION_BY_CODE` (`stage_strip.js`) — every existing refusal code has an entry in both; the two new codes (`CI_TIMEOUT`, `HEAD_MOVED`) get one each, following the exact existing pattern, not a new mechanism.

**Why this is the simplest sufficient approach:** the gap is a single missing step — after `rebaseAndRetest` pushes a new commit, nothing waits for *that* commit's checks before `gh pr merge` is called. Everything needed to close it already exists in parts (a rollup reader, a polling idiom, a failure-classification shape); the fix is one new orchestration function plus two small existing-file extensions, not a new subsystem.

**Where it spends/saves:** polling `gh pr view` costs a small, bounded number of lightweight GraphQL calls. Given this repo's own documented sensitivity (`CONTEXT.md` "GitHub request budget", 5,000 pts/hour, exhausted three times in 2026-10), poll interval is set to 30s (not tighter), capping worst-case use at roughly 260 points for one timed-out gated merge — a small fraction of budget, and only paid when a rebase actually happened.

**Phone-OS / capability direction:** this is pure reliability plumbing for a system Gil doesn't want to babysit — it removes a failure mode that otherwise reliably strands a rebased PR at the last step, turning "approve and move on" into "approve, then come back and approve again." Strictly makes MARVIN more self-reliant, not less; no human judgment is displaced (nothing here decides *whether* code is good, only waits for GitHub's own verdict on it).

**Machine:** no machine-placement question — this is webhook-server (Node) logic, already running wherever the merge gate runs today; nothing changes about which Mac does what.

## Tests first

All new/changed tests live in `dashboard/test/ci_status.test.js` and `dashboard/test/merge.test.js` unless noted, following each file's existing mocking conventions (fake `exec`, injected `sleep`, no real timers).

**Pure helpers (`ci_status.test.js`):**
1. `requiredCheckNames` returns every name regardless of `where` (unlike `gateCheckNames`, which filters to `both`); a missing/broken/empty required-checks.json returns `[]`, same as `gateCheckNames`.
2. `requiredCheckState`: all required names present and passing → `passing`; one present and failing → `failing`, naming only it; a required name **absent from the rollup entirely** → `pending` (a check that never started is not yet a failure); a non-required check in the rollup is ignored entirely, even if failing; a stale+fresh rerun of the same name dedupes to the newest (reuses `ciState`'s existing `newer()` logic — confirm it still applies through the filter).

**`waitForRequiredChecks` (new, `merge.js`; unit tests in `merge.test.js`) — one test per bullet in "How we'll try to break it," plus misuse:**
3. No required names (project has no required-checks.json) → resolves immediately, **zero** `exec` calls (empty input).
4. Checks still queued, then pass on a later poll → resolves after the expected number of sleeps, no earlier/later.
5. A required check reports `FAILURE` → throws `MergeFailure{code:'CI_FAILED'}` naming exactly that check; no further polling.
6. A required name that **never appears** in the rollup through to the deadline → throws `CI_TIMEOUT` naming it explicitly as never reported (distinct wording from "still running").
7. `headRefOid` changes between two polls (something else pushed to the branch while waiting) → throws `HEAD_MOVED` immediately, does not wait out the remaining budget, does not attribute it to the PR's code.
8. A cancelled run on the **same** sha (no push, just a cancellation) → falls through to the existing `ciState` FAILED-set handling and reports `CI_FAILED`, not `HEAD_MOVED` (only a changed sha gets that code).
9. `gh pr view` throws or returns unparseable JSON on some polls (rate limit / blip) → treated as inconclusive for that poll only, loop continues, succeeds once a later poll returns clean data.
10. `gh pr view` fails on **every** poll until the deadline (sustained outage) → times out as `CI_TIMEOUT`, with a message distinguishing "couldn't read GitHub's checks" from "checks didn't finish."
11. All required checks already green on the very first poll → resolves with zero `sleep` calls (no gratuitous waiting).
12. Never itself calls `gh pr merge` (pure wait, no merge side effect) — regression guard against scope creep.

**`mergePrUnqueued` integration (`merge.test.js`, new describe block alongside the existing "merging waits for the repo's own CI"):**
13. AC1 — gate:true, `rebaseAndRetestFn` resolves `{ok:true, sha}`, required checks pending-then-passing on that sha → `gh pr merge` is eventually called, result `merged:true`.
14. AC2 — same, but a required check fails on the rebased sha → `{merged:false, reengaged:true, code:'CI_FAILED', stage:'gate'}`, `reengage` called naming the check, `gh pr merge` **never** called.
15. AC3 — required checks never resolve before a short test-injected timeout → throws `CI_TIMEOUT`; `reengage` is **not** called (machine/GitHub issue, not the PR's); `gh pr merge` never called — mirrors the existing "gate that never finishes" test's assertions.
16. `!gate` path (no rebase needed) → the new wait never runs at all; no new `gh pr view` calls beyond the existing pre-gate check (regression guard that the ungated path is untouched).
17. `rebaseAndRetestFn` resolves `{ok:true}` with **no** `sha` (every existing mocked-gate test) → wait is skipped; confirms the ~15 pre-existing gate:true tests in this file need no changes.
18. A project clone with no `.github/required-checks.json` (not yet opted in) → wait is a no-op, merges exactly as before.
19. A flaky-but-passed gate run (`result.flaky` non-empty) still goes through the wait afterward — the flaky path isn't a silent bypass.
20. Stage/timeline: `CI_FAILED`-after-rebase, `CI_TIMEOUT`, and `HEAD_MOVED` all record `gate:failed` (reusing the existing stage name, not inventing one) before resolving/throwing, so the ticket timeline never silently stops.

**`rebaseAndRetest` regression (existing tests in `merge.test.js`, updated because the return shape changes — "verify fails when code changes without a test changing"):**
21. The three existing `expect(result).toEqual({ ok: true })` assertions (clean rebase; flaky-push-retry; generated-file-conflict-resolved) gain a `sha` field, verified against the fixture's **actual** new remote sha (`currentRemoteSha`), not just a shape check.
22. The squash-merge (`mergeInstead`, #1183) success path also returns `sha` alongside `merged: true`.

**Queue/UI consistency (existing files — confirm names first, then extend):**
23. `merge_order.js`: `HOLD_UNTIL.CI_TIMEOUT === 'later'`, `HOLD_UNTIL.HEAD_MOVED === 'head'`; `outcomeFor` with these codes returns `kind:'hold'` (not `'failed'` — a held PR auto-retries instead of being dropped from the queue).
24. `stage_strip.js`: `remediationFor('CI_TIMEOUT')` and `remediationFor('HEAD_MOVED')` return non-null, non-generic text (guards against a blank tooltip for the new codes).

## Decisions

None. Every choice below was derivable from existing code rather than a genuine fork: the required-name source (`required_checks.py:names()`'s semantics, mirrored in JS), the failure codes and their `action` (`CI_FAILED`→reengage matching the existing pre-gate handling; `CI_TIMEOUT`/`HEAD_MOVED`→escalate matching `GATE_INFRA`/`MEMORY_PRESSURE`), and the timeout default (65 min — longer than the slowest required check's own `timeout-minutes: 60` in `.github/workflows/ci.yml`, so the wait is never what gives up first).

## Task List

1. `ci_status.js`: factor `gateCheckNames`'s file-read into a shared `readChecks(dir)`; add `requiredCheckNames(dir)` (all names, not just `where: both`) built on it.
2. `ci_status.js`: add `requiredCheckState(rollup, names)` — filters the rollup to `names`, feeds the match set through the existing `ciState`, and treats any name with zero matching entries as `pending`.
3. `merge.js`: add `waitForRequiredChecks(prUrl, exec, { names, sha, sleep, timeoutMs, pollMs, now, progress })` — polls `gh pr view --json statusCheckRollup,headRefOid`, detects a changed `headRefOid` (→ `HEAD_MOVED`), classifies via `requiredCheckState` (→ `CI_FAILED` naming the check, or keep polling), and gives up at the deadline (→ `CI_TIMEOUT`, wording a sustained read-failure differently from "didn't finish"). No-ops instantly when `names` is empty.
4. `merge.js`: `rebaseAndRetest` — after the retest passes and before/around the push, capture `git rev-parse HEAD` in the scratch worktree and include it as `sha` in every `{ok: true, ...}` return (plain push, force-push, and the `mergeInstead` path alike).
5. `merge.js`: `mergePrUnqueued` — inside the existing `if (gate) { ... }` block, after the flaky/clean-pass stage recording, compute `requiredCheckNames(ctx ? ctx.clone : REPO_PATH)`; when non-empty and `result.sha` is present, call `waitForRequiredChecks`. On `CI_FAILED`, reuse the exact reengage/`recordFailureFn`/`stage('gate','failed', …)` shape already used for the pre-gate `CI_FAILED` catch. On any other `MergeFailure` (`CI_TIMEOUT`, `HEAD_MOVED`), record `stage('gate','failed', …)` then rethrow unchanged (mirrors `GATE_INFRA`/`MEMORY_PRESSURE`).
6. `merge_order.js`: add `CI_TIMEOUT: 'later'` and `HEAD_MOVED: 'head'` to `HOLD_UNTIL`.
7. `stage_strip.js`: add `CI_TIMEOUT` and `HEAD_MOVED` entries to `REMEDIATION_BY_CODE`.
8. Update the 3 existing `rebaseAndRetest` tests whose `toEqual({ok:true})` now needs a `sha`; add the new test(s) covering the squash-merge path's `sha`.
9. Write the new `ci_status.test.js` cases (items 1–2 above) and the new `waitForRequiredChecks` + `mergePrUnqueued` integration cases (items 3–20 above) in `merge.test.js`, plus the `merge_order.js`/`stage_strip.js` cases (23–24).
10. `CONTEXT.md`: add a dated bullet after "## GitHub CI is now part of the merge decision (2026-10-06)" describing the new post-rebase wait, its two new codes, and the reused-but-distinct relationship to `assertChecksGreen`'s pre-gate check (which ignores exactly the checks this one waits for).
11. Run the full Python + dashboard suites locally before opening the PR (per `feedback-full-suites-before-hand-merge` — a hand-merge skips CI's own gate).