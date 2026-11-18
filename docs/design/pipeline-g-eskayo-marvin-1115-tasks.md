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