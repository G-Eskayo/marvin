## North-star fit

**Reuses:** the whole fix is new glue between two already-tested building blocks, no new subsystem:
- `checkRuns()` / `ciState()` in `dashboard/webhook-server/ci_status.js` (dedup of reruns, the `FAILED` conclusion set) — I reuse `checkRuns()` directly instead of re-parsing `statusCheckRollup` myself.
- The `assertChecksGreen` → catch‑`CI_FAILED`‑→‑`reengage` wiring already in `mergePrUnqueued` (`dashboard/webhook-server/merge.js:906-919`) — the new post‑push wait is wired with the *identical* try/catch shape, just for a second moment in the flow.
- `gateCheckNames()`'s read-a-JSON-list-of-names pattern (`ci_status.js:97-104`) — the new `requiredCheckNames()` is a one-line variant of it (no `where==='both'` filter), mirroring `lib/required_checks.py names()` exactly rather than inventing a second vocabulary.
- `postGateStatus`'s existing "fetch `headRefOid` right after the push" call — same trust assumption, no new API shape.

**Why this is the simplest sufficient approach:** the bug is purely sequencing — `rebaseAndRetest` pushes a brand-new commit and `mergePrUnqueued` calls `gh pr merge` on it immediately, before GitHub's own Actions runs for that commit have even started. Branch protection's required contexts (`lib/branch_protection.py settings()`) are the *full* name list in `.github/required-checks.json`, not the `where:"both"` subset `gateCheckNames()` returns (today they're numerically equal because no check currently has `where:"ci"`, but they mean different things — using `gateCheckNames()` for this would be a silent future bug once a CI-only check is added). So I add exactly one small reader (`requiredCheckNames`) and one small poller (`awaitRequiredChecks`), and insert one `try { await … } catch {}` block, right where the existing post-rebase code already does its stage bookkeeping. No new stage name, no new timeout framework, no change to `rebaseAndRetest` itself.

**Resource cost:** adds a bounded number of cheap `gh pr view` calls (one if GitHub's already green, up to the timeout/poll ratio in the worst case) per *gated* (rebased) merge only — not per merge. No model/token spend. It *saves* resources once #826 turns branch protection on, by replacing "every gated merge fails at the last step and escalates to a human" with a normal wait-then-merge.

**Phone-OS / capability fit:** this is pipeline plumbing, not user-facing; its contribution to north star 2 is removing a reliability gap (nothing should break silently once main is protected) rather than making anyone more capable or more passive.

**Machine:** runs inside the existing webhook process (`dashboard/webhook-server`), on whichever Mac already runs that repo's merge gate — unchanged by this ticket.

**No open Decisions.** I checked for forks that need Gil's input and found none that aren't already answered by precedent in this file:
- *Does the wait apply when `gate===false`?* No — nothing new was pushed, so GitHub's existing status for the unchanged head commit is unaffected; this already matches the existing `assertChecksGreen` behavior for that path.
- *Does a required-check failure send the ticket back for rework (reengage), or just refuse?* Reengage — identical to how the **pre-rebase** `CI_FAILED` from `assertChecksGreen` already behaves (`merge.js:906-919`); extending the same policy to the post-rebase commit is not a new judgment call.
- *What if the PR's branch moves to a different commit while we wait (someone else pushes)?* Refuse rather than merge a commit the gate never tested — the only correct option, not a toss-up.

## Tests first (ci_status.test.js unless noted)

For `requiredCheckNames(dir)`:
1. Returns every name in `.github/required-checks.json` regardless of `where` (including a hypothetical `where:"ci"` entry) — proves it differs from `gateCheckNames()`, which would drop it.
2. Missing file, invalid JSON, `checks` not an array, an entry missing `name` → `[]`, never throws (misuse/malformed input).
3. Duplicate names, and a name containing regex-special characters (e.g. `"C++ tests (x86)"`) → returned verbatim, unharmed by later plain-string matching.

For `awaitRequiredChecks(prUrl, exec, names, opts)`:
4. `names` is `[]` (no required-checks.json, or a project that lists none) → resolves immediately, zero `exec` calls.
5. All required checks already `SUCCESS`/`SKIPPED`/`NEUTRAL` on the first poll → resolves after exactly one `exec` call.
6. A check starts `QUEUED`/`IN_PROGRESS` and later reports `SUCCESS` → resolves only after it reports done; proves it actually waits (**"checks that are still queued"**).
7. A check reports `CANCELLED` on the pinned commit → throws `MergeFailure` `CI_FAILED` naming it (**"a cancelled run"**, reusing the existing `FAILED` set — not a new classification).
8. One of several required checks fails while others are still pending → throws `CI_FAILED` immediately, naming only the failed one(s) — fails fast, doesn't wait out the rest.
9. A required name never once appears in the rollup for the whole run → `CI_TIMEOUT` after the stated limit, naming it (**"a required name CI never reports"**) — not a hang.
10. Two required names never report → `CI_TIMEOUT` names both, not just one.
11. An old failing run for a check is superseded by a newer passing run of the same name → resolves passing (proves it reuses `checkRuns()`'s rerun-dedup, not a naive scan that would false-positive).
12. `exec` rejects (or returns non-JSON) on every single poll until the deadline, with **no successful read ever** → resolves (fails open) rather than blocking a merge on a metadata outage (**"GitHub returning errors or rate limits"**).
13. `exec` rejects a few times, then returns a valid all-green answer → resolves normally; a transient blip doesn't abort the wait early.
14. The PR's `headRefOid` changes between polls (a newer push landed) → throws `MergeFailure` `HEAD_MOVED`, never returns success, even if the checks it now sees are all green (**"a newer push"**) — refuses rather than merging an untested commit.
15. `timeoutMs`/`pollMs`/`sleep`/`now` are all injectable (no real timers in the test), matching this file's existing `mergeableNow`-style DI.

For `mergePrUnqueued` (merge.test.js), injecting a stub via `deps.awaitRequiredChecksFn`:
16. `gate === false` (no rebase) → `awaitRequiredChecksFn` is never called; merge proceeds exactly as today (no regression on the existing fast path).
17. `gate === true`, stub resolves → `requiredCheckNames(ctx ? ctx.clone : REPO_PATH)` was passed the right directory for both the marvin-native (`ctx` null) and cross-project (`ctx.clone`) cases, and `gh pr merge` is still called afterward.
18. `gate === true`, stub throws `CI_FAILED` with a linked ticket → `reengage` is called naming the failing check(s), `gh pr merge` is **never** called, result is `{ merged:false, reengaged:true, code:'CI_FAILED' }`.
19. Same, but no ticket number (hand-authored PR) → falls through to a bare throw, no `reengage` call — mirrors the existing no-ticket `CI_FAILED` behavior for `assertChecksGreen`.
20. `gate === true`, stub throws `CI_TIMEOUT` → propagates as a rejected `MergeFailure`, `gh pr merge` never called, **no** `stage('gate','failed', …)` recorded — same precedent as the existing `CI_PENDING` path.

## Task List

1. In `dashboard/webhook-server/ci_status.js`: add `requiredCheckNames(dir)` (full name list, no `where` filter), extract the shared "read `.github/required-checks.json`" logic so `gateCheckNames` and `requiredCheckNames` don't duplicate the try/parse.
2. In the same file: add `REQUIRED_CHECKS_TIMEOUT_MS` / poll-interval constant and `awaitRequiredChecks(prUrl, exec, names, opts)`, built on `checkRuns()`, implementing: immediate return on empty `names`; per-poll classification into failing / not-yet-done; pinned-sha tracking from the first successful read with a `HEAD_MOVED` refusal if it changes; `CI_FAILED` refusal naming failing checks; `CI_TIMEOUT` refusal naming never-finished checks after the deadline, but fail-open if not even one successful read was ever obtained.
3. Write the `ci_status.test.js` cases (1–15 above) against the real functions.
4. In `dashboard/webhook-server/merge.js`: import `requiredCheckNames, awaitRequiredChecks`; add `awaitRequiredChecksFn = awaitRequiredChecks` to the `deps` destructure in `mergePrUnqueued`.
5. In the `if (gate) { … }` block, right after the existing `stage('gate', 'passed', …)` / flaky-comment handling and before `postGateStatus(...)`, add the `try { await awaitRequiredChecksFn(prUrl, exec, requiredCheckNames(ctx ? ctx.clone : REPO_PATH)) } catch (e) { … }` block, mirroring the existing pre-rebase `CI_FAILED` → `reengage` handling (catch `CI_FAILED` with a ticket, record the stage/failure, reengage and return; anything else — including `CI_TIMEOUT`/`HEAD_MOVED` — rethrows unchanged).
6. Write the `merge.test.js` integration cases (16–20 above).
7. Run the full dashboard test suite (`cd dashboard && npx vitest run`) and the repo's Python suite, since both are required checks for this repo itself.