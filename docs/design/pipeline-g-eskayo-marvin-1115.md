## North-star fit

**Reuses:** `dashboard/webhook-server/ci_status.js`'s `ciState(rollup, { ignore })` and `gateCheckNames()` (marvin#1099/#1100) for gate-covered filtering — only wires the same `ignore: gateCovers` the queue line (`merge_order.js:ownReason`, line 154) already uses into the two places the ticket names: `mr_review.js`'s `ownBlocker` (line 258) and the `checks:` field in `listPipelinePrs` (line 404). Reuses `rebase_status.js`'s disk-memory shape (`~/.claude/logs/*.json`, read/write + TTL cleanup) for the new "one re-run per head SHA" record, and `stack_retarget.js`'s shape (a rate-limited, try/catch-per-item, never-throws `.check(prs)` object wired into `index.js`'s `mr:list` handler beside the existing `stackRetarget.check(prs)` call) for the new background no-runner-retry pass. Also reuses the Python pipeline's existing principle (`lib/ticket_pipeline.py:_failing_checks`, CONTEXT.md:1664 — "cancelled/timed-out is the runner's fault, not the code's") as the precedent for treating non-`FAILURE` conclusions as re-run candidates, though the JS-side `FAILED` set in `ci_status.js` itself is intentionally left untouched (out of scope: the ticket only asks to add a narrower no-runner *layer* on top, not to change what already counts as "failing").

**Simplest sufficient approach:** no new always-on service. The no-runner check rides the same poll/refresh tick that already lists PRs (`mr:list`), exactly like the stacked-PR safety net. The "no rerun loop" guarantee comes from one small on-disk JSON file keyed by `repo#number@headSha@runId`, not a new daemon or state machine.

**Where it spends tokens/API calls:** one extra `gh api .../annotations` call only for checks that are *already* failing with a non-`FAILURE` conclusion (cancelled/timed-out/etc.) and not gate-covered — the common case (a green PR, or a real test failure) costs nothing extra, since real `FAILURE` conclusions are classified without ever calling the annotations endpoint.

**User impact:** removes a false alarm and a dead end (Gil currently has to go ask "do I approve on GitHub instead?"); the card now tells him exactly what's true and either fixes it itself (one re-run) or says plainly that it needs him — more capable, not more passive, and no new manual step is added for the cases that *are* real failures.

**Machine:** no machine-specific code; this runs wherever the dashboard's electron main process already runs the `mr:list`/`stackRetarget` loop (both Macs). The `pullOnly` (box) guard that already prevents `stackRetarget` from acting on GitHub is reused verbatim for the new retry, since re-running a check is also an action on GitHub the box must never take (ADR 0069).

## Files already read

`dashboard/electron/main/mr_review.js`, `dashboard/src/lib/prState.js`, `dashboard/webhook-server/ci_status.js`, `dashboard/webhook-server/merge_order.js`, `dashboard/webhook-server/gh_watch.js`, `dashboard/webhook-server/rebase_status.js`, `dashboard/electron/main/stack_retarget.js`, `dashboard/electron/main/index.js` (relevant sections), `dashboard/electron/main/approve_guard.js`, `dashboard/electron/main/pr_order.js`, `dashboard/test/ci_status.test.js`, `dashboard/test/stack_retarget.test.js`, `dashboard/test/pr_state.test.js` (relevant sections), `lib/ticket_pipeline.py` (`_failing_checks`), `CONTEXT.md:1664`, `docs/agents/decisions-format.md`. Verified live against a real open PR that `gh pr view/list --json statusCheckRollup` already returns `detailsUrl` in the form `https://github.com/{owner}/{repo}/actions/runs/{runId}/job/{jobId}` for every `CheckRun` entry, so no new `--json` fields are needed anywhere.

## Design decisions I'm making (not deferring)

- A check's GitHub `conclusion` of `FAILURE` always means a real failure — never eligible for no-runner reclassification, and an annotations call is never made for it (cheaper, and directly satisfies "a real failure with a capacity-warning annotation still reads as a failure" without needing to inspect that check's own annotations at all).
- Only `CANCELLED` / `TIMED_OUT` / `STARTUP_FAILURE` / `ACTION_REQUIRED` conclusions are *candidates*; a candidate is only classified `'no-runner'` when GitHub posted at least one annotation and **every** annotation on it matches GitHub-side wording (e.g. "not acquired by Runner", "cancelled ... by GitHub"). Zero annotations, a 404, or any one annotation that doesn't match (including a person's manual-cancel note) → ordinary failure treatment, no re-run. This is what makes "cancelled by a person" and "capacity warning next to a failing-test annotation" both resolve correctly without extra special-casing.
- If **any** of a PR's currently-failing, non-gate-covered checks has conclusion `FAILURE`, the whole PR is treated as a real failure and the no-runner flow is skipped entirely for it (no annotation calls, no rerun) — a genuinely broken PR is never shown as "GitHub couldn't run it" just because one *other* check on the same commit also happened to lose a runner.
- The re-run key is `repo#number@headSha@runId` (not just `@headSha`): GitHub Actions re-running a workflow run keeps the same run id, so this still gives "one re-run per head SHA" in the common case (all of marvin's checks share one CI run), while correctly isolating two independent workflow runs on the same commit.

## Decisions

<!-- marvin:decisions -->
### recurrence-probe: The ticket's Recurrence check asks for a probe counting MR Review cards stuck in `checks-failed` for a gate-covered or no-runner reason, read from an "MR Review state log" that doesn't exist yet. Build it now, or defer?
- [ ] A: Build it in this PR (new state log of each card's `kind` over time + a probe function registered with `lib/incident_ladder.py`/`purpose_metrics.py`, check date 2026-11-26)
- [ ] B: Defer to a follow-up ticket filed from this PR (this PR ships the fix the acceptance criteria actually require; the log/probe is new standing infrastructure, not named in "What to build" or the acceptance criteria)

## Tests to write first

Mirroring the ticket's "How we'll try to break it" + its Attacks list, plus the misuse categories not already covered there:

1. **`ci_status.test.js` — `failingCheckRuns(rollup, { ignore })` (new export):**
   - Returns `{name, conclusion, detailsUrl}` only for `CheckRun` entries with `status: 'COMPLETED'` and a conclusion in the existing `FAILED` set.
   - A `StatusContext` entry is never returned (no rerunnable id).
   - A gate-covered name is excluded, matching `ciState`'s own `ignore` semantics exactly (same fixtures as the existing "ciState with checks the gate covers" describe block).
2. **New `check_annotations.test.js`:**
   - `parseRunAndJobId('https://github.com/o/r/actions/runs/123/job/456')` → `{runId: '123', jobId: '456'}`; a URL without `/job/` or `null`/empty input → `null` (**attack: malformed/missing `detailsUrl`**).
   - `classifyFailure([])` → `'failure'` (**attack: annotations endpoint returns an empty list while logs are still processing**).
   - `classifyFailure([{title:'...'}, ...])` with a single "not acquired by Runner"-style annotation → `'no-runner'`.
   - `classifyFailure(...)` with a no-runner annotation *and* a real failing-test annotation on the same check → `'failure'` (**ticket's explicit break-it case**).
   - `classifyFailure(...)` with an annotation that is neither no-runner wording nor a recognizable failure (e.g. a person's manual-cancel note) → `'failure'` (**attack: cancelled by a person**).
   - `fetchAnnotations`: `gh` throwing (404) → `[]`, not a thrown error (**attack: 404**); `gh` returning non-JSON → `[]` (**attack: malformed response**).
3. **New `no_runner_rerun.test.js`** (mirrors the shape `rebase_status.js` would be tested with — read/write round trip):
   - Write then read returns the same entry under its exact key.
   - Two different `(repo, number, headSha, runId)` keys never collide, including two different repos sharing the same `headSha` string (**ticket's explicit break-it case**).
   - An entry older than the TTL is dropped on the next write (**attack: unbounded growth / stale state**).
   - Reading a missing or corrupt file returns `{}`, never throws (**attack: malformed/missing state file**).
4. **New `no_runner_retry.test.js`** (mirrors `stack_retarget.test.js`'s style exactly):
   - First sighting of a no-runner-classified failing check → calls `gh(['api', 'repos/{repo}/check-runs/{jobId}/annotations'])` then `gh(['run', 'rerun', '{runId}', '--repo', repo, '--failed'])` exactly once, records `result: 'reran'`.
   - Second `.check()` call with the same key still no-runner → does **not** call `run rerun` again, flips the record to `result: 'asked'` (**ticket: "ask once, not re-run again"**).
   - Third `.check()` call with `result: 'asked'` already on disk → makes zero `gh` calls at all (**attack: repeated polling must never loop**).
   - `gh(['run', 'rerun', ...])` throws (rate limit / permission refusal) → records `result: 'refused'`, and a later `.check()` call makes no further rerun attempt (**ticket's explicit break-it case; attack: dependency failure**).
   - Annotations call returns `[]` or throws → no record written, no rerun, check falls through untouched (**attack: 404 / still-processing logs**).
   - A PR with one no-runner-eligible check **and** one real `FAILURE`-conclusion check on the same commit → zero `gh` calls, nothing written (**ticket's explicit break-it case**).
   - A gate-covered check name (via `gateCoversFor`) → excluded before any annotation call (**reuses #1099's ignore list; attack: wasted API calls on checks nothing waits for**).
   - Two PRs, two different repos, same `headSha` string → each gets independently exactly one rerun (**ticket's explicit break-it case**).
   - A thrown error from `gh` on the annotations call (not just the rerun call) → caught, logged, never thrown out of `.check()` (**attack: dependency failure; concurrency** — a slow/failing tick must not kill the next poll's tick, mirroring `stackRetarget`'s `running` guard is NOT needed here since this is pure per-call, but errors-never-escape must hold).
5. **`mr_review.test.js` additions:**
   - A PR whose only failing checks are all gate-covered → `listPipelinePrs(...)`'s returned `checks.state` is `'passing'` (not `'failing'`), matching acceptance criterion 1 (**reuses the existing gate-covers fixtures from `ci_status.test.js`**).
   - `ownBlocker`/`prsForOrderCheck` (via `prsForOrderCheck`'s existing test file) likewise returns `blocked: null` for a gate-covered-only failure (**attack: the Approve-click order check must agree with the card, per marvin#209's existing rule**).
   - A PR with a matching on-disk no-runner record (`result: 'reran'`) and no real failure among its checks → the returned PR carries `noRunner: {checkName, result: 'reran'}`.
   - The same PR, but with its `headRefOid` changed (a new push) → `noRunner` is `null` (stale record for an old commit is never shown — **attack: stale state**).
   - A PR with a no-runner record present **and** a real `FAILURE` check also failing → `noRunner` stays `null` even though the disk record exists (belt-and-suspenders against a stale/racing disk write — **attack: a person's mistake / race with the background writer**).
6. **`pr_state.test.js` additions/updates:**
   - Update the two existing assertions that check the old `"It is sent back for rework automatically..."` / `/^a\. It is sent back/` text (lines 52-57, 72-77) to assert the corrected wording, and explicitly assert the new text never contains the string `"sent back"` (acceptance criterion 4).
   - `pr.noRunner = {checkName: 'Python tests', result: 'reran'}` → `kind: 'checks-not-run'`, `tone: 'wait'`, `approve: 'hidden'`, `deny: 'enabled'`, headline/detail mention the check name and never say "sent back."
   - `result: 'asked'` and `result: 'refused'` → `kind: 'checks-not-run'`, `tone: 'blocked'`.
   - `queueLineFor` with a `checks-not-run` card and a merge-queue `reason` matching `^checks failing\b` → suppressed (new `SAID_BY_HEADLINE['checks-not-run']` entry), consistent with how `'checks-failed'` already suppresses it.

## Task List

1. `dashboard/webhook-server/ci_status.js`: add `failingCheckRuns(rollup, { ignore })`, exported, pure.
2. New `dashboard/webhook-server/check_annotations.js`: `parseRunAndJobId`, `isNoRunnerAnnotation`, `classifyFailure`, `fetchAnnotations(repo, jobId, gh)` — pure classification + one thin IO wrapper, all best-effort (never throws).
3. New `dashboard/webhook-server/no_runner_rerun.js`: `NO_RUNNER_RERUN_PATH`, `noRunnerKey(repo, number, headSha, runId)`, `readNoRunnerReruns(file)`, `recordNoRunnerRerun(key, entry, file, now)` — mirrors `rebase_status.js` exactly, including its 7-day TTL cleanup.
4. New `dashboard/electron/main/no_runner_retry.js`: `createNoRunnerRetry({ gh, gateCoversFor, now, log })` with a `.check(prs)` mirroring `createStackRetarget`'s shape — per-PR, per-run try/catch, never throws; implements the first-sighting/already-reran/already-asked/already-refused state machine above.
5. `dashboard/electron/main/mr_review.js`:
   - `ownBlocker(pr, uiPathsFor, gateCoversFor = () => null)` — pass `{ ignore: gateCoversFor(pr.repo || MARVIN_REPO) }` into `ciState`.
   - `markBlocked` / `prsForOrderCheck` — thread the new `gateCoversFor` param through, default `() => null` (no behavior change for existing callers that don't pass it).
   - `listPipelinePrs`: hoist the `mergeQueue()` fetch above the final `.map()` so `gateCoversFor` is available there too; use it for the `checks:` field; read `readNoRunnerReruns()` once and attach `pr.noRunner` per the rules in "Design decisions" above.
6. `dashboard/electron/main/index.js`:
   - Construct `noRunnerRetry = createNoRunnerRetry({ gh: (args) => ghOut(args), gateCoversFor: ..., log: ... })`, deriving `gateCoversFor` from the same `getMergeQueue()` already defined (reuse, don't duplicate).
   - Wire `noRunnerRetry.check(prs)` into the `mr:list` handler beside `stackRetarget.check(prs)`, under the same `!fixturePrs && !pullOnly` guard.
   - Thread a `gateCoversFor` into the `prsForOrderCheck(...)` call in the `mr:approve` handler (await `getMergeQueue()` once there too), so the Approve-click order check agrees with the card (marvin#209).
7. `dashboard/src/lib/prState.js`:
   - Reword the `ci.state === 'failing'` branch to drop the false "sent back for rework automatically" claim.
   - Add a `pr.noRunner` branch (placed before the `ci.state === 'failing'` check) producing the new `checks-not-run` kind, with `tone: 'wait'`/Deny-enabled for `'reran'` and `tone: 'blocked'` for `'asked'`/`'refused'`.
   - Add `'checks-not-run': /^checks failing\b/` to `SAID_BY_HEADLINE`.
8. Write all tests in the "Tests to write first" list before each corresponding implementation step (TDD red→green), then run the full dashboard test suite.
9. If Decision `recurrence-probe` comes back **A**: add the MR Review card-state log + a probe function wired into `lib/incident_ladder.py`/`purpose_metrics.py` with check date 2026-11-26. If **B**: file the follow-up ticket and link it from this PR.