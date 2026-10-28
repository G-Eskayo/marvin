## North-star fit

**Reuses:** `error_log.record()` (`lib/error_log.py`, already the standard "never silent" path — ADR/marvin#422, and already globally stubbed in `lib/tests/conftest.py:_isolate_error_log`, confirming it's the live convention every failure path is expected to use, not something new); `disk_ledger.du_kb()` (`lib/disk_ledger.py`) for the scratch-worktree disk measurement, rather than writing a second `du` wrapper; `mutation_check.merge_bodies()`'s idempotent-section-replace shape (`lib/mutation_check.py:290`) for writing the new "why unscored" text into a PR body — generalized to take its marker strings as parameters instead of writing a second near-duplicate function; `auto_merge_shadow.pick_unscored()`'s existing oldest-first, stale-on-new-commit selection (`lib/auto_merge_shadow.py:181`) is kept as the selection rule, just called in a loop instead of once; `_Locked`'s existing flock pattern for all new state fields. No new top-level file or module — everything lands inside `lib/auto_merge_shadow.py`, which already owns this concern.

**Simplest sufficient:** the actual defect is narrow — one PR is scored per hourly run, and a failing attempt is swallowed to stderr with no "move to the next PR" and no durable record, so one stuck PR (or just volume) stalls the whole queue. I verified this isn't hypothetical: PR #368 (open since 2026-10-09, 100% JS changed lines) has carried `Score: unknown (nothing could be scored...)` for over two weeks — `mutation_score()` returns `None` for that text, so `verdict()` reports it as "pending" forever even though the mutation checker has already conclusively decided it can never be scored (JS isn't mutation-tested yet). That's a real, confirmed bug, not a guess. The fix is a bounded loop + a reason classifier + reuse of the logging/disk primitives already in the repo — no new subsystem.

**Tokens:** spends a little more (the reason-classifier text, the generalized `merge_bodies`), saves a lot downstream — Gil currently has to open 21 PRs by hand to find out why nothing merges; this makes the cause visible on the PR itself. Verification must **not** try to run the real mutation check against all 21 live PRs inside the build/verify session — that is exactly what blew the previous attempt's 900 s budget (`claude -p` timed out mid-run). The fix ships as code; the next few real hourly cron runs (which have no 900 s cap) drain the backlog for real after merge.

**User capability:** leaves Gil more able to trust the pipeline unattended — a PR either gets a score or a stated, visible reason within a day, closing the exact gap (#644) that currently forces him to manually audit the backlog.

## What I found investigating (read, not assumed)

- Only 11 PRs are open right now (not 27 — several merged/closed since the issue was filed), so AC1's "21" is already a smaller, live number.
- `#368`: conclusively unscoreable (JS-only diff) but reported as merely "pending" — the real bug.
- `#600`: correctly scored (67%, below the 80% bar) and correctly waiting for Gil — not a bug, confirms `verdict()` works when a score exists.
- `_score_one()` scores exactly one PR per `run()` call and swallows any exception to stderr only (`lib/auto_merge_shadow.py:224-225`); nothing is written to `scored` on failure, so the *same* oldest unscored PR is retried every hour forever if it keeps failing — this single-PR, no-skip-forward design is what turns "slow" into "stuck" at volume.
- This ticket was attempted twice before and failed both times (read from the issue's own comments): once on code review after 3 iterations (no specifics available), and once on an unhandled 900 s subprocess timeout — almost certainly from trying to run the live 21-PR backlog pass synchronously inside the build session. My plan avoids repeating that by never running the real backlog scan as part of verification.

## Tests to write first

Mapped to the ticket's explicit misuse list (a crashing mutant run, a timeout, a PR closed while it's being scored) plus ADR 0063's full catalogue, using real collaborators (the actual `error_log`, `disk_ledger`, `mutation_check.merge_bodies`) wherever a mock would hide their rules, and only mocking `subprocess`/`gh`/`mc.run_mutation_check` at the true I/O boundary:

1. **Crashing mutant run** — `mc.run_mutation_check` raises; the scan catches it, calls `error_log.record(...)`, and still moves on to try the next unscored PR in the same run.
2. **A timeout** — `git fetch`/`worktree add` raises `subprocess.TimeoutExpired`; caught and logged, and the scratch worktree is still removed (regression test on the existing `finally` cleanup, since this ticket touches that code path directly).
3. **A PR closed while being scored** — `gh pr edit` fails because the PR/branch vanished mid-attempt; caught and logged, run continues, and the PR naturally drops out of the next run's fresh `gh pr list --state open`.
4. **The backlog reproduces and drains** (AC2, literal) — a synthetic 21-PR backlog, run the real multi-PR loop for N simulated hourly runs at the chosen `scan_budget`, assert every PR ends up scored or reason-stated within 24h of its (fake) `createdAt`.
5. **One bad PR doesn't starve the queue** — a PR that always fails is skipped *within the same run* so a different, younger unscored PR gets scored instead (today's code can't do this: only one PR is attempted per call).
6. **A failed attempt is retried later, not abandoned** — same PR, same `headRefOid`, still eligible for `pick_unscored` on the next run since `scored[url]` was never set on failure.
7. **A conclusively-unscoreable PR gets a stated reason immediately** — `mc.run_mutation_check` returns `status="unknown"`/all-JS `unmeasured`; the reason is written to the PR without waiting the 24h grace period (this is deterministic now, not a timing issue) — the direct fix for `#368`'s bug.
8. **The 24h boundary, both sides** — a genuinely-still-queued PR at 23h59m gets no reason-stated noise; at 24h01m with still no score it does.
9. **Idempotent stated-reason** — the same PR/cause/commit never gets a second comment or a second body rewrite; a new commit or a changed cause does re-fire.
10. **Cost is measured and survives a bad reading** — wall-clock via `time.time()`, disk via `disk_ledger.du_kb()` on the scratch dir before removal; when `du_kb` returns a `"not measured (...)"` string (protected/timed out), the scan and the `step(...)` line still complete without crashing.
11. **Huge/malformed PR body** — an oversized or binary-garbled body doesn't break `mutation_score()` or the reason classifier's regex/parsing.
12. **Concurrency** — two overlapping scans via the existing `_Locked` flock leave `scored` and the new `reason_stated` state consistent (no double-post, no lost update) — extends the existing lock-fixture pattern already in the test file.
13. **Stale state** — a `scored` entry pointing at an old `headRefOid` after a rebase must trigger a fresh score attempt *before* any stated-reason logic runs (combines the existing staleness rule with the new classifier so it can't fire prematurely).
14. **A person's mistake** — Gil hand-edits a PR body and strips the `<!-- marvin:mutation-check -->` markers; `merge_bodies` (generalized) and `mutation_score` must not crash, and must cleanly re-add a fresh section.
15. *(ADR 0063's "wrong permissions or machine" is not applicable here — nothing in this change touches machine identity or runs anywhere but the mini's existing hourly scan; noted rather than silently skipped.)*

Verify must fail if `lib/auto_merge_shadow.py` changes without a matching change in `lib/tests/test_auto_merge_shadow.py`.

## Decisions
<!-- marvin:decisions -->
### scan_budget: How much should one hourly scan score, at the cost of more disk/CPU on the mini for that hour?
- [ ] A: Stay at 1 PR scored per run (same pace as today), just fix the skip-forward-on-failure bug — slowest drain (~24 PRs/day worst case), lightest load
- [ ] B: Up to 3 PRs per run, bounded by a 20-minute wall-clock budget — roughly 3× faster drain, moderate load
- [ ] C: As many PRs as fit in a 40-minute wall-clock budget per run (up to ~4 at worst case) — fastest drain, heaviest load on the hourly scan

### stated_reason_channel: Where should "why this PR isn't scored" show up?
- [ ] A: A PR comment each time a cause is newly stated (visible in the PR's own timeline)
- [ ] B: A body section (like the existing Mutation Score block), replaced in place on re-evaluation
- [ ] C: Both — a body section for the dashboard/MR Review card to parse, plus a one-time comment for visibility
<!-- /marvin:decisions -->

## Task List

1. `lib/auto_merge_shadow.py`: wire `error_log.record(source="auto_merge_shadow", ...)` into the scoring exception handler (keep the existing `stderr` print alongside it).
2. `lib/mutation_check.py`: generalize `merge_bodies(current_body, new_section, start_marker=..., end_marker=...)` with today's mutation-check markers as the defaults, so the new reason section reuses it instead of a parallel function.
3. `lib/auto_merge_shadow.py`: refactor `_score_one` into `_score_one_pr` (same body, returns success/failure + detail instead of swallowing) and a new `_score_many(prs, repo, path, budget_sec)` loop that calls `pick_unscored` repeatedly, skipping within the same run past any PR whose attempt failed, until `budget_sec` (from the `scan_budget` decision) is spent.
4. Measure and persist cost: wall-clock via `time.time()` around `_score_many`; disk via `disk_ledger.du_kb(scratch, timeout=...)` on each scratch worktree right before its removal; surface both in the `step(...)` line in `lib/ticket_pipeline.py:_auto_merge_shadow` and in the persisted `last_report`.
5. Add `why_unscored(pr, now, scored, error_log_entries)` reason classifier: immediate "conclusively unscoreable" when `mc.run_mutation_check`'s result shows nothing is Python/scoreable; otherwise only after 24h open with no score, classified as queued-behind-N / mutation-check-unavailable / repeated-failure (from `error_log`) / unknown.
6. Add the idempotent stated-reason write (format per the `stated_reason_channel` decision), guarded by a `reason_stated` flag (cause + commit) in the shadow state so it never repeats for the same PR/cause/commit and re-fires only when either changes.
7. Write all 15 tests above first in `lib/tests/test_auto_merge_shadow.py`, confirm they fail against the current code, then implement steps 1–6 to make them pass.
8. Update `lib/auto_merge_shadow.py`'s and `lib/mutation_check.py`'s module docstrings and `CONTEXT.md`'s Auto-merge section with the concrete, decided `scan_budget` and the measured per-scan time/disk cost, replacing the vague "each check can take 10 minutes" language.
9. Run the full test suite plus the new tests; do **not** run the real scoring pass against the live 21-PR backlog inside this session (that caused the previous attempt's 900 s timeout) — the merged code drains it for real on the next scheduled hourly scans.
10. Run `graphify update .` after the code changes.