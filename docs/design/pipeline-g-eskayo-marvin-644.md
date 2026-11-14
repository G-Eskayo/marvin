## North-star fit

- **Reuses, before adding anything new:**
  - `lib/mutation_check.py:render_section`/`merge_bodies` — the PR already gets an "unknown (reason)" Mutation Score section when the check can't score something. The current gap is that this path is *never reached* when `_score_one` fails before calling `run_mutation_check` (git fetch/worktree/`gh pr edit` exceptions are swallowed to `stderr` only). The fix routes those failures through a synthetic `{"status": "unknown", ..., "reason": cause}` result into the *same* renderer — no new marker, no new "stated-reason channel" decision (the two prior failed attempts both invented one; I didn't need to).
  - `lib/error_log.py:classify()` — already has regex causes for network/disk/permission/auth/rate-limit failures. Reused directly to turn a git/gh exception into the human-readable cause AC1 asks for, instead of writing a parallel classifier.
  - `lib/ticket_policy.py:retry_backoff_s()` — the exact exponential-backoff-by-attempt-count math `run_ticket.py` already uses for failed ticket builds. Reused for repeated scoring failures instead of inventing new backoff logic. `run_ticket.py`'s `MAX_CONSECUTIVE_FAILURES`/park-after-N pattern is reused the same way, so a permanently-broken PR stops burning scan budget every hour without being silently dropped.
  - `lib/disk_ledger.py:du_kb()` — reused as-is (own timeouts, own "not measured (...)" sentinel) to measure scratch-worktree disk cost; no new disk-walking code.
  - `lib/auto_merge_shadow.py:pick_unscored()` and its "new commit = new score" semantics are reused unchanged for both the scoring queue and the backoff skip (a PR temporarily "in backoff" is just merged into the same `scored`-shaped lookup for the duration of one run).
- **Simplest sufficient approach:** one outer try/except per PR, in a bounded multi-PR loop, writing through the one existing rendering path. No new state files, no new PR-comment channel, no new markers.
- **Tokens:** spends a small, capped amount of model/CI time once (this implementation); saves recurring token/GitHub-API cost going forward by scoring several PRs per hourly tick instead of one, and by not re-attempting a permanently-broken PR every hour forever.
- **Leaves Gil more capable:** the backlog, its cause, and its cost become visible and self-draining instead of a thing he has to notice and ask about — exactly the "constant workflow" M1 asks for.
- **Machine:** stays on the mini (where `auto_merge_shadow.run()` already executes hourly); no change to where this runs.

**Note on ticket currency:** the live shadow state (`~/.claude/logs/auto-merge-shadow.json`, read directly) shows auto-merge was actually switched **on** by Gil on 2026-11-10, and the specific 21-PR backlog from 2026-10-25 has long since drained (its `scored` map now covers essentially every historical PR, including the three currently open: #1277/#1278/#1279). The *literal* 21-PR backlog named in the ticket's "What" is stale. The underlying defect it was filed against — one-PR-per-hour scoring with silent, unlogged, unretried-sanely failures — is still live in the code exactly as described, so the ticket is still valid; I'm fixing the mechanism, not re-litigating a backlog that's already gone.

## Decisions

None. Each place a prior attempt (per the ticket's comments) apparently needed a Decision — how to write the stated reason, how big a scan budget to use — already has a precedent-backed default elsewhere in this codebase (above), so I'm applying those defaults directly rather than asking:
- Stated-reason channel → the existing Mutation Score PR-body section (already reviewed, PR #351).
- Scan time budget → 480s (8 min) per hourly tick, leaving headroom for the rest of `_run_ticket_agents`; documented, not asked, same status as `MIN_SCORE=80`, `SHADOW_DAYS=3`, `wall_clock_budget_sec=600` already hardcoded nearby.
- Failure cap before "parked" wording → 5, matching `run_ticket.py`'s `MAX_CONSECUTIVE_RETRIES`.

## Tests (written first, `lib/tests/test_auto_merge_shadow.py`)

**AC3's named attacks:**
1. A crashing mutation run (`run_mutation_check` raises) is logged, a cause is written into the PR body, and the run continues to the next PR.
2. A timeout in a git/mutation sub-step is classified, logged, and doesn't hang the whole scan.
3. A PR closed mid-scoring (`gh pr edit` fails because it's closed) is logged and skipped, not fatal to the loop.

**Each dependency failing:**
4. `git fetch` fails (network down) → classified via `error_log.classify`'s existing network pattern, logged, moves on.
5. `git worktree add` fails (disk/collision) → same handling.
6. `gh pr edit` fails (rate limit / expired auth) → classified via existing `error_log.CAUSES` patterns, logged, moves on.
7. A freshly-created/missing state file (no `scored`/`scoring_failures` keys yet) doesn't crash the new scan logic.

**Retry and backoff, never silent:**
8. A PR that keeps failing gets exponential backoff via `ticket_policy.retry_backoff_s` — not re-attempted before its `not_before`, attempted again after.
9. After 5 consecutive failures it's treated as "parked" (stated, not retried every run) but a new push (new `headRefOid`) resets the counter and revives it at once.

**Backlog drains (AC2, the central test):**
10. A reproduced backlog of >20 unscored PRs fully drains within a bounded number of simulated hourly runs, comfortably inside 24 (one day).
11. One scan can score several PRs (not just one) up to the time budget, oldest-first, and stops once the budget is spent.

**Stated reason (AC1):**
12. Regression: when `run_mutation_check` itself concludes "unknown" (no mutable lines / no test file / no merge base), the existing body-section behavior is unchanged by the refactor.
13. New: an infrastructure exception (not an in-engine "unknown") still gets a human-readable cause written into the same section, via `error_log.classify`.

**Cost stated (AC4):**
14. A scan's wall-clock elapsed and disk KB are measured (fake clock, fake `disk_ledger.du_kb`) and surfacedin the persisted state and the `step()` line.
15. A `disk_ledger.du_kb` "not measured (...)" string return doesn't crash cost formatting/reporting.

**Misuse, concurrency, stale state, permissions:**
16. A malformed PR dict (missing `headRefOid`/`body`) is logged and skipped, not fatal.
17. A backlog far larger than one run's budget still makes oldest-first forward progress without exceeding the budget.
18. Two back-to-back scans (simulating overlapping/retried hourly runs) don't double-score or corrupt state (idempotent via the existing lock + `scored` map).
19. A permission-style failure (`EPERM`/"Operation not permitted") is classified and handled like any other dependency failure.
20. A backoff/park counter for an old commit doesn't suppress scoring after the PR is pushed to a new commit (mirrors the existing "new commit = new score" test).
21. Corrupted `scoring_failures`/`scored` structures (wrong type) are read defensively, not trusted to crash the run.

## Task List

1. `lib/auto_merge_shadow.py`: add `SCAN_BUDGET_SEC = 480` and `MAX_SCORE_FAILURES = 5` constants, documented with reasoning (hourly tick headroom; precedent value from `run_ticket.MAX_CONSECUTIVE_RETRIES`).
2. Add `_classify_failure(exc)` — thin wrapper over `error_log.classify()` (reused, not reimplemented).
3. Refactor `_score_one` into `_score_one_pr(pr, repo, path)`: same scratch-worktree/git/mutation-check flow as today, but (a) on success, behavior unchanged; (b) on any exception, classify + `error_log.record(source="auto_merge_shadow", ...)`, build a synthetic `{"status": "unknown", ..., "reason": cause}` result, write it through the existing `mc.render_section`/`merge_bodies`/`_gh pr edit` path (itself wrapped so a failed write is also logged, never raised); (c) measure elapsed time and `disk_ledger.du_kb(scratch, ...)` right before the worktree is removed; always returns a result dict, never raises.
4. Add `_score_many(prs, repo, path, budget_sec=SCAN_BUDGET_SEC, now=None)`: loop calling `pick_unscored` (merging in an in-memory view of `scored` + currently-backed-off PRs so a PR in backoff is skipped this run without being falsely marked scored), score via `_score_one_pr`, update `scored` / `scoring_failures` (with `ticket_policy.retry_backoff_s`-computed `not_before`, park wording after `MAX_SCORE_FAILURES`) under the existing `_Locked` block, accumulate elapsed/disk cost, stop at budget or empty queue. Returns a summary (`scored`, `failed`, `elapsed_sec`, `disk_kb`).
5. `run()`: replace the `_score_one(prs, repo, path)` call with `_score_many(prs, repo, path)`; persist its summary as `st["last_scan"]` in the same locked block that already writes `last_report`. Keep `run()`'s own return type (`seen`, the per-PR verdict list) unchanged so `main()`'s `run` subcommand and existing tests keep working.
6. Add a small `last_scan(path=STATE_PATH)` accessor mirroring the existing `mode()`/`report()` style, for `ticket_pipeline.py` to read.
7. `lib/ticket_pipeline.py:_auto_merge_shadow`: extend the existing `step("Auto-merge shadow", ...)` line to include the scan's scored/failed count and elapsed/disk cost from `auto_merge_shadow.last_scan()`.
8. Write all 21 tests above first in `lib/tests/test_auto_merge_shadow.py` (existing file, reused, not a new one), confirm they fail against current code.
9. Implement steps 1–7 to make them pass; run the full existing test file plus the new tests green.
10. Update `auto_merge_shadow.py`'s module/`_score_many` docstrings to replace the "one per hourly run... 10 minutes" language with the real multi-PR, budget-bounded behavior and its worst-case time/disk bound (mirroring `disk_ledger.py`'s own documented-cost style).
11. Add one bullet to `CONTEXT.md`'s "Auto-merge" section stating the scan budget, the backoff/park behavior, and that failures are now logged and stated in the PR body (no ADR amendment — this is a robustness fix to the already-decided ADR 0064 design, not a new policy).
12. Run `graphify update .` after the code changes.