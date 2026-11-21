## North-star fit

**Reuses:** `ciState(rollup, { ignore })` in `dashboard/webhook-server/ci_status.js:13` (marvin#1099) — already does exactly what "gate-covered checks are information only" needs; the bug is that `ownBlocker()` (`mr_review.js:258`) and the `checks` field built in `listPipelinePrs()` (`mr_review.js:404`) call it with no `ignore`, while `merge_order.js`'s `ownReason()` (line 154) and `enrichForOrder()` already thread `gateCovers` correctly. I also reuse `rebase_status.js`'s exact read/write-JSON-with-pruning pattern for the new "one re-run per head SHA" disk store, and the `handleSafetyRequest({method,url,body}, run) -> {status,json}` shape (`safety_labels.js`) for the new HTTP handler. No new abstraction is added where these already fit.

**Simplest sufficient approach:** the classification (is this failure "no runner" or real) is a pure read, so it runs where PR lists already get read — the dashboard's existing check-watch trigger (`electron/main/index.js:309`, CONTEXT.md "Triggers over polling") already re-reads a PR's list the moment its checks change, for every open PR, not just queued ones. No new timer, no new polling loop (`polling_guard.test.js` stays green). The one *mutating* action (`gh run rerun`) follows this app's existing rule that the dashboard is a trigger, not an executor (mr_review.js:20-24, same shape as `approveMr`/`denyMr`): Electron classifies and POSTs; the webhook server (the one Mac already doing every other GitHub mutation) is the sole place that calls `gh run rerun` and owns the dedup file, so two Macs' dashboards open at once still cause at most one real rerun.

**Token/compute cost:** two extra `gh api` reads only while a check is actually failing and not gate-covered (rare); zero added cost once gate-covered checks are ignored (today they cost a false, blocking re-render on every PR). No new background loop.

**Phone-OS direction:** none of this is Mac-only logic; the classification and rerun trigger are plain HTTP + `gh`, reachable from mobile-backend later the same way `/approve` already is.

**More capable, not more passive:** removes a chore (Gil asking "should I approve on GitHub instead?") and a false alarm, without hiding a real failure — a genuine test failure next to a capacity-warning annotation still blocks, by design.

## Decisions

<!-- marvin:decisions -->
### mobile_scope: Should this ticket also wire `dashboard/mobile-backend/dashboard_gh_api.js`'s `listPipelinePrs` call with `mergeQueue`/the new no-runner trigger?
- [ ] A: No — it doesn't pass `mergeQueue` today either (marvin#1099/#1100 never wired it, a pre-existing gap), so mobile already shows the pre-#1099 behavior for gate-covered checks. Leave it; file a follow-up ticket.
- [ ] B: Yes — wire `mergeQueue` and the no-runner classifier into the mobile route too, in this PR.

## Tests written first

**From "How we'll try to break it":**
1. Annotations endpoint returns 404 / throws, or an empty array, while logs are still processing → `isNoRunnerCheck([])` is `false` → ordinary `checks-failed`, no rerun attempted.
2. A real failing-test annotation alongside a "runner capacity" warning annotation on the same check → `isNoRunnerCheck` is `false` (not every annotation matches) → still reads as a failure.
3. `gh run rerun` rejected (non-zero exit / rate limit / permission) → `triggerNoRunnerRerun` returns `{rerun:'refused', message}`, **and records the attempt** so a later call for the same (repo, number, sha) does not call `gh run rerun` again.
4. Re-run already recorded for this (repo, number, sha) and the check is still no-runner → classification returns `rerun:'already-tried'`, no second `gh run rerun` call, card asks the owner.
5. An annotation whose text says "cancelled ... by a person" / "cancelled by <username>" (no "GitHub") → `isNoRunnerAnnotation` is `false` → not treated as no-runner even though the check's conclusion is `CANCELLED`.
6. Two different repos with PRs sharing the same head SHA → two independent dedup-store entries, keyed `repo#number@sha`; both get exactly one rerun each.

**Acceptance criteria as tests:**
7. `ownBlocker`/`markBlocked` with `gateCovers` containing the only failing check's name → returns `null` (not "GitHub checks failed").
8. `listPipelinePrs`'s per-PR `checks` field, built with `{ignore: gateCoversFor(repo)}`, has `state: 'passing'` when the only failure is gate-covered; `describePrState` on that PR is `kind:'ready', approve:'enabled'`, and its `note` mentions GitHub's own (failing) result for that check.
9. A no-runner failure on an uncovered check: `describePrState` returns `kind:'checks-not-run'`, headline names the check, and the orchestrator attempted exactly one rerun.
10. A second refresh with the same head SHA and the same failure: the classifier still returns the no-runner names, but `rerun` is `'already-tried'` and no second `gh run rerun` call happened (assert the injected `exec`/rerun stub's call count).
11. `describePrState`'s `checks-failed` branch (a real, non-gate-covered, non-no-runner failure) no longer contains the string "sent back for rework" — update the two existing assertions in `pr_state.test.js` (`/^a\. It is sent back/` etc.) to the corrected wording.
12. `queueLineFor`: a PR in `checks-not-run` whose merge-queue reason is `"checks failing: …"` hides that duplicate line (extend `SAID_BY_HEADLINE`), same as `checks-failed` already does.

**Misuse the ticket's list didn't spell out:**
13. Bad/malformed input: `exec` for `gh api .../check-runs` returns non-JSON stdout, or `check_runs` is missing/not an array; annotations response is not an array or contains non-object entries — all fall through to `[]`/ordinary-failure, never throw.
14. Each dependency failing: the check-runs fetch throws (gh/network down) → `[]`; the annotations fetch throws → `[]`; the `/no-runner-rerun` POST itself fails or times out from Electron's side → `listPipelinePrs` still returns the card with `noRunner: null` (falls back to plain `checks-failed`), never rejects the whole list build (same best-effort contract as `rebaseStatus`/`autoMergeShadow`).
15. Concurrency: two overlapping POSTs to `/no-runner-rerun` for the same (repo, number, sha) (simulated with a slow `exec`) → the second sees the first's disk record and does not call `gh run rerun` a second time.
16. Stale state: a new push changes the head SHA → the old sha's dedup entry doesn't apply; the new sha is treated as never-tried (one fresh rerun allowed).
17. A run id that can't be parsed from `details_url` (missing field, unexpected URL shape) → `triggerNoRunnerRerun` returns `refused` with a clear message and still records the attempt (no retry loop).
18. `required-checks.json` missing/broken (existing `gateCheckNames()` → `[]`) → `ownBlocker`/`checks` degrade exactly as before (nothing ignored), confirmed with a test at the new call sites, not just the old ones.

## Task List

1. `dashboard/webhook-server/no_runner.js` (new): `isNoRunnerAnnotation`, `isNoRunnerCheck`, `fetchCommitCheckRuns({repo, sha, exec})`, `fetchCheckAnnotations({repo, runId, exec})`, `runIdFromDetailsUrl(url)`, `classifyFailingChecks({repo, sha, failingNames, exec})`. Never throws.
2. `dashboard/webhook-server/no_runner_rerun.js` (new): `NO_RUNNER_RERUN_PATH`, `readNoRunnerReruns`, `recordNoRunnerRerun` (prune >7 days, same pattern as `rebase_status.js`), `triggerNoRunnerRerun({repo, number, sha, runId, exec, file})`, `handleNoRunnerRerunRequest({method, url, body}, {exec, file})`.
3. Wire `POST /no-runner-rerun` into `dashboard/webhook-server/index.js`, reusing `readBody` with a small size cap, same shape as the `/safety` route.
4. `dashboard/webhook-server/ci_status.js`: no code change; confirm via test that `ownBlocker`/the `checks` builder now call it with `ignore`.
5. `dashboard/electron/main/mr_review.js`: `ownBlocker(pr, uiPathsFor, gateCovers)`; `markBlocked(prs, uiPathsFor, gateCoversFor)`; reorder `listPipelinePrs` to fetch `queue` before `markBlocked`/the final map; thread `gateCoversFor(repo)` into `checks` (plus a `gateCoveredFailing` list for the note) and into `ownBlocker`; add injected `noRunnerRerun` (default no-op) called per PR with currently-failing, non-covered check names, attaching `pr.noRunner`.
6. `dashboard/electron/main/index.js`: implement the real `noRunnerRerun` — classify via `no_runner.js` using `execFileAsync`, memoize per `${pr.url}@${headSha}` in-memory to avoid re-reading once a verdict is known, POST to `MR_WEBHOOK_URL`'s `/no-runner-rerun` sibling when classification finds a no-runner check; wire it into both `mrList` and `pipelineCardFromMemory`'s `listPipelinePrs` calls (which already pass `mergeQueue`).
7. `dashboard/src/lib/prState.js`: new `checks-not-run` branch (checked before `ci.state === 'failing'`) covering `rerun: 'started' | 'already-tried' | 'refused'`; drop the false "sent back for rework" claim from the `checks-failed` branch; surface `ci.gateCoveredFailing` as a note on the `ready` path; add `'checks-not-run'` to `SAID_BY_HEADLINE`.
8. Tests: `dashboard/test/no_runner.test.js`, `dashboard/test/no_runner_rerun.test.js` (new); update `dashboard/test/mr_review.test.js` and `dashboard/test/pr_state.test.js` per the list above.
9. Resolve the `mobile_scope` decision once answered, then wire (or explicitly skip + file the follow-up ticket for) `dashboard/mobile-backend/dashboard_gh_api.js`.
10. Update the recurrence probe (issue's "Recurrence check") to count MR Review cards in `checks-failed` whose only failing checks are gate-covered or no-runner, from the MR Review state log.