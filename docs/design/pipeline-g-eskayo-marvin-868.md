## North-star fit

**Reuses before adding anything new:**
- `ci_status.js`'s `checkRuns()`/`checkRow()` (existing, tested) for classifying a GitHub check run's done/passed/failed state — the new wait logic calls this instead of writing a second parser.
- `merge.js`'s `mergeableNow()` pattern (bounded poll, injectable `sleep`, "unreadable → still unknown, keep polling") — the new `waitForRequiredChecks` is the same shape, one more bounded poll loop in a file that already has two (`mergeableNow`, the 3-attempt merge retry).
- `merge.js`'s `baselineFails`/`diskFirstAid`/`memoryCheck` deps convention: each defaults to `null` (no-op) inside `mergePrUnqueued`, and is wired to its real implementation only in `index.js`'s one production call site. This is reused *specifically* so the ~30 existing `mergePrUnqueued`/`mergePr` unit tests in `dashboard/test/merge.test.js` that already exercise `gate:true, rebaseAndRetestFn → {ok:true}` keep passing unmodified: none of them inject the new dep, so the wait stays a no-op for them, exactly like it is today for `memoryCheck`.
- `mergePrUnqueued`'s existing CI_FAILED pre-gate block (~line 910) and post-test-failure block (~line 980) for the exact "stage → recordFailureFn → reengage → structured return" shape; and the GATE_INFRA/MERGE_REFUSED shape (`refusal(code, 'gate', message, remediation)`, default action `'escalate'`, no reengage) for the new timeout outcome.
- `gateCheckNames(dir)` (unchanged) for the set of required-check names — the same list `postGateStatus` already consumes at the exact call site I'm extending.

**Why this is the simplest sufficient approach:** branch protection (the parent of #826) makes GitHub itself refuse `gh pr merge` until its own named check runs report success *on the exact commit being merged* — that's enforced server-side, not something our webhook can route around. The gate already knows which names those are (`required-checks.json`) and already posts a status on that exact commit (`postGateStatus`, directly above the insertion point); the only missing piece is to actually wait for GitHub's copy of those same names before calling `gh pr merge`, and to turn "still running" / "failed" / "never reports" into the same three outcomes the rest of this file already has words for (wait, `CI_FAILED`, a named timeout).

**Where it spends/saves:** it *reintroduces* exactly the GitHub-capacity dependency that `marvin#1099`/PR #1100 removed on purpose ("the gate is the check... a GitHub capacity problem can't hold the queue any more") — but only for the post-rebase case, and only because branch protection makes it mandatory, not optional. That tension isn't something to route around; it's already been decided at the ticket level (#826 explicitly sequences branch protection *after* #868 closes, i.e. Gil has already chosen to accept this trade-off for the rebase case). I'm flagging it here because it's real, not because it's still open — see Decision 2 below for the one tunable that actually matters once it's accepted.

**Phone-OS / capability:** none directly — this is merge-infrastructure correctness, not something Gil interacts with. It does make `#826`'s branch protection safe to turn on, which is a prerequisite for "main stays green" (north star 2's reliability precondition).

**Machine:** no change — same webhook-server process (Mini/MacBook) that already runs the gate.

## Tests I will write first

In `dashboard/test/ci_status.test.js`, a new `describe('waitForRequiredChecks (marvin#868)')`:
1. All required checks already `SUCCESS` → resolves `{ok:true}` immediately, `sleep` never called.
2. One required check `FAILURE` → `{ok:false, code:'CI_FAILED', names:['<that check>']}`.
3. One required check `CANCELLED` → also `CI_FAILED` (ticket: "a cancelled run").
4. A required check `QUEUED`/`IN_PROGRESS` on poll 1, `SUCCESS` on poll 2 → waits it out, resolves `{ok:true}` (ticket: "checks still queued").
5. A required name that never appears in the rollup at all (not merely pending — absent) → counted as pending, not silently passing; with a stepped fake `now()`, eventually `{ok:false, code:'CI_TIMEOUT', names:[...]}` once the time limit passes (ticket: "a required name CI never reports").
6. `exec` throws, or returns unparseable JSON, on some polls → doesn't throw, keeps polling, resolves `{ok:true}` once a later poll succeeds (ticket: "GitHub returning errors or rate limits").
7. `exec` *always* throws/unparseable → bounded by the stepped fake clock, ends in `{ok:false, code:'CI_TIMEOUT', ...}` rather than looping forever — proves "never hangs the merge queue" at the unit level.
8. `headRefOid` changes between two polls (someone else pushed to the branch while waiting) → refuses immediately, naming it moved, rather than silently evaluating the wrong commit (ticket: "a cancelled run (a newer push)", read as a stale-target race).
9. Empty/absent `names` → `{ok:true}` without calling `exec` at all (malformed/empty input).
10. A `SKIPPED`/`NEUTRAL` conclusion on a required check counts as satisfied, matching the *existing* `ciState` convention ("skipped and neutral count as fine") rather than inventing new semantics.
11. A failing check that is **not** in the required `names` list is ignored (the function only watches what it's told to).

In `dashboard/test/merge.test.js`, a new `describe('after a rebase, the gate waits for GitHub's required checks (marvin#868)')`:

A. `waitForChecks` dep resolves `{ok:true}` → merges as before, `gh pr merge` called.
B. `deps.waitForChecks` **omitted** (the default) → still merges as today, proving the feature is opt-in and every pre-existing test (none of which pass this dep) is unaffected.
C. `waitForChecks` resolves `{ok:false, code:'CI_FAILED', names:['Python tests'], reason}` → `reengage` called, comment names the check, result `{merged:false, reengaged:true, code:'CI_FAILED'}`, `gh pr merge` never called.
D. `waitForChecks` resolves `{ok:false, code:'CI_TIMEOUT', ...}` → rejects with `MergeFailure({code:'CI_TIMEOUT', action:'escalate'})`, `reengage` **not** called, `gh pr merge` never called (machine/CI problem, not the PR's fault — same framing as `GATE_INFRA`).
E. `gate:false` (no rebase) → `waitForChecks` spy is **not** called at all (locks in the scoping from Decision 1 below; flips if the owner picks option A).
F. Stage recording: `gate:started`, `gate:failed` on a `CI_FAILED` wait outcome, nothing after (mirrors the existing "no false merging/done events" test).
G. A project-profile PR (`ctx`, e.g. clarity-captions) also waits, using that project's clone's `required-checks.json` names — confirms this isn't marvin-only, matching the ticket's "in both repos."

## Decisions
<!-- marvin:decisions -->
### scope: Should the wait also cover a merge that *doesn't* rebase (gate: false)?
Today a no-rebase merge never waits for GitHub's copy of the gate-covered checks (marvin#1099's ignore-list). Once branch protection is on, GitHub can still refuse `gh pr merge` here too if those checks haven't finished on the *existing* head — it just degrades gracefully today (a named `BRANCH_PROTECTION`/escalate error already exists in `failure.js`, not a silent bad merge). The ticket's AC text only says "the rebased commit."
- [ ] A: Extend the same wait to every merge (rebase or not), so branch protection can never surface as a raw GitHub error anywhere
- [ ] B: Scope this ticket strictly to the rebase path (what the AC asks for); file a fast follow-up ticket for the no-rebase path

### timeout: How long should the gate wait for GitHub's required checks before giving up (CI_TIMEOUT)?
Merges are serialized per repo (`repoQueues` in `merge.js`): whatever this waits, every *other* approved PR for the same repo waits behind it too. PR #1100's own data: successful CI historically took a median of 10 minutes, up to 65 when GitHub's runners were short on capacity.
- [ ] A: 20 minutes — favors queue throughput; a legitimately-slow-but-healthy CI run can be wrongly timed out during a GitHub capacity blip, needing a manual re-approve
- [ ] B: 70 minutes — favors not spuriously refusing a good PR (covers the worst historically-observed case plus margin); a genuinely stuck check blocks the queue for over an hour
- [ ] C: 35 minutes (middle ground)

## Task List

1. `dashboard/webhook-server/ci_status.js`: add `REQUIRED_CHECKS_WAIT_MS` (+ a module-level poll-interval constant) and `export async function waitForRequiredChecks(prUrl, names, exec, opts)`, reusing `checkRuns()` for classification; polls `gh pr view --json headRefOid,statusCheckRollup`, pins the first-seen `headRefOid` as the target, and returns `{ok:true}` / `{ok:false, code:'CI_FAILED', names, reason}` / `{ok:false, code:'CI_TIMEOUT', names, reason}`.
2. Write the `ci_status.test.js` tests (1–11 above) against that function.
3. `dashboard/webhook-server/merge.js`: in `mergePrUnqueued`, add `waitForChecks = null` to the `deps` destructure; after the existing `postGateStatus(prUrl, exec, checkNames)` call (hoisting `checkNames` into a local so both calls share it), call `waitForChecks(prUrl, checkNames)` when provided, and branch on its result into the existing reengage-shaped (`CI_FAILED`) or escalate-shaped (`CI_TIMEOUT`, via `refusal()`/`MergeFailure`) outcomes.
4. Write the `merge.test.js` tests (A–G above) against that integration.
5. `dashboard/webhook-server/index.js`: import `waitForRequiredChecks` from `./ci_status.js` and add `waitForChecks: (url, names) => waitForRequiredChecks(url, names)` to the deps object passed to `mergePr`, alongside `baselineFails`/`diskFirstAid`/`memoryCheck`.
6. Apply the owner's `scope` decision: if A, thread the same wait into the `gate:false` branch too (and add/adjust the corresponding merge.test.js cases); if B, leave a one-line note in `merge.js` pointing at the follow-up ticket.
7. Set `REQUIRED_CHECKS_WAIT_MS` to the owner's `timeout` decision.
8. Add a dated `CONTEXT.md` entry (near the existing "GitHub CI is now part of the merge decision" / "the gate is the check" history) documenting that branch protection requires the named checks on the exact merged commit, and that the gate now waits for them after a rebase push rather than relying on its own local retest.
9. Run the full dashboard test suite (`npm test` under `dashboard/`) to confirm no regressions in the ~30 pre-existing `mergePrUnqueued`/`mergePr` tests that exercise the gated-rebase-success path.