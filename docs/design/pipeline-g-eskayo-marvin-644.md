Now I have everything needed to write the plan.

## North-star fit

**Reuses:** `lib/error_log.py:record()` (the existing "never silent" failure-logging primitive — already used across webhook/code-sync/dashboard failures) for scoring failures instead of inventing new logging; `lib/disk_ledger.py:du_kb()` (the existing bounded, niced disk-measurement primitive, built for exactly this "state the space cost" need) instead of writing a new `du` wrapper; `auto_merge_shadow.py:pick_unscored()` (already selects the oldest unscored PR correctly, including rescoring after a push) unchanged; `lib/owner_decisions.py`'s pattern — trigger off the existing hourly scan, no new loop, a `<!-- marvin:... -->` marker for idempotence, GitHub (or the existing shadow-state JSON) as the record rather than new local state — reused for the new "stated reason" comment instead of designing a fresh mechanism.

**Simplest sufficient approach:** investigation (see below) shows the 21-unscored backlog is a **throughput** problem, not a data-loss or correctness bug: `_score_one` scores exactly one PR per hourly scan (a reviewed decision from PR #351) against a 27-PR pool, so with ongoing reworks re-queuing PRs, the queue structurally cannot drain in a day. I considered also "fixing" `mr_raiser.py`'s rework path, which overwrites a PR's body (losing any already-written mutation-check section) — but on inspection this is *already correct*: a reworked PR's code has genuinely changed, so a stale carried-forward score would be a false "well-tested" signal for untested new code, exactly the kind of assumed-not-verified claim the north stars forbid. I'm deliberately **not** touching `mr_raiser.py`. The real fix is: score more than one PR per scan (bounded, so cost stays stated and capped), log failures through the existing never-silent primitive instead of `stderr`-only, and post one stated-reason comment on any PR still unscored past 24h (satisfies AC2's "or a stated reason" literally, using AC1's investigation as the reason categories).

**Tokens/cost:** spends a bounded, explicitly-stated amount of extra mini CPU/GitHub-API time per scan (more PRs scored per hourly run) to buy down the correctness risk of auto-merge waiting indefinitely on stale "pending" PRs; saves tokens by never re-deriving the backlog cause by hand again (`disk_ledger.du_kb` + wall-clock are measured and reported, not asserted in prose, so Health/dashboard can read real numbers going forward).

**User impact:** more capable — it unblocks #343 (auto-merge executor) truthfully rather than by papering over the backlog, and failures become visible instead of silently rotting in stderr.

## Investigation (answers AC1)

- `lib/auto_merge_shadow.py:_score_one()` scores **one** unscored PR per call; it's invoked once per hourly scan via `ticket_pipeline.py:_auto_merge_shadow()`. Against an open-PR pool of 27–34 (per the live `~/.claude/logs/auto-merge-shadow.json`), and with reworked PRs (sent back, rebuilt, re-pushed) re-entering the unscored pool via `pick_unscored()`'s sha-mismatch check, 1/hour cannot clear the backlog within a day once it's this size. **This is "too slow," not "failing" or "skipped."**
- Failures inside `_score_one` (git fetch/worktree/mutation-run exceptions) are caught and only `print(..., file=sys.stderr)`ed — never written to `~/.claude/logs/errors.jsonl` via `lib/error_log.py`, so a PR stuck because scoring keeps crashing is indistinguishable from one stuck because it just hasn't been reached yet.
- `mutation_check.run_mutation_check`'s own crash/timeout handling (`per_mutant_timeout_sec`, `wall_clock_budget_sec`) is already covered by `lib/tests/test_mutation_check.py` (`test_a_real_timeout_is_reported_as_timeout`, `test_a_planted_bug_that_hangs_times_out_and_counts_as_caught`) — not re-tested here; only the orchestration layer's reaction to an *unexpected* exception from that call is untested.

## Decisions

```markdown
## Decisions
<!-- marvin:decisions -->
### scan_budget: How many PRs should one hourly scan score, and what's the time cap?
- [ ] A: Up to 3 PRs per scan, 10 min cap each (≤30 min added to the scan; clears a 27-PR backlog in ~9 h)
- [ ] B: Up to 5 PRs per scan, 10 min cap each (≤50 min added; clears in ~6 h, more mini CPU/API use per scan)
- [ ] C: Uncapped per-PR count, bounded only by a 20-minute total scan-level wall-clock budget (adapts to PR size automatically)

### stated_reason_channel: Where should the "still unscored after 24h" explanation go?
- [ ] A: One PR comment (idempotent, marker-guarded) — visible on GitHub directly
- [ ] B: A line in the existing shadow-state JSON only, surfaced through the dashboard/MR Review card (no new PR comment)
```

Until answered I will implement **A/A** (3 per scan, PR comment) as the safer, cheaper default — least new GitHub-comment noise, smallest cost increase — and both are trivially swappable constants/branches if the owner picks differently.

## Tests to write first

1. `test_a_crashing_scoring_attempt_is_logged_not_silent` — monkeypatch the scoring call to raise; assert `error_log.record` (or its on-disk effect) fires with the PR number, the PR stays unscored, and the state file isn't corrupted.
2. `test_a_timed_out_scoring_attempt_is_logged_and_retried` — same shape, simulating `subprocess.TimeoutExpired`; next scan still offers that PR via `pick_unscored`.
3. `test_a_pr_closed_mid_scoring_is_dropped_not_stuck` — PR present in the list fetched at scan start, but the follow-up `gh pr edit` fails because it closed meanwhile; assert no crash, it's logged, and it's simply absent (not retried forever) once a later `run()` is given an open-PR list that no longer contains it.
4. `test_a_scan_scores_several_prs_up_to_its_time_budget_not_just_one` — several unscored PRs queued, fake scorer takes a fixed simulated duration; assert the scan stops once the configured budget is reached, oldest-first.
5. `test_repeated_simulated_hourly_scans_drain_a_27_pr_backlog_within_a_day` — the AC2-mandated reproduction: seed ~27 unscored PRs (mixing fresh and "reworked"/sha-changed ones), run the scoring step repeatedly simulating 24 hourly ticks with a fake scorer, assert every PR ends up either scored or carrying a stated reason by tick 24.
6. `test_mutation_check_not_installed_states_that_reason_rather_than_staying_silently_pending` — `ImportError` path; after 24h a stated reason naming "mutation check unavailable on this machine" is recorded/posted, not left as bare "pending".
7. `test_a_stated_reason_comment_is_posted_once_and_never_duplicated` — run the 24h-stated-reason step twice for the same still-unscored PR; assert only one comment/flag is produced (idempotent via marker or state flag), covering "repeats."
8. `test_a_pr_not_yet_24h_old_gets_no_stated_reason_comment` — boundary/misuse case: a brand-new unscored PR must not be flagged early (covers "a person's mistakes" reading an early flag as a failure signal).
9. `test_corrupt_or_unreadable_state_file_during_the_bigger_scoring_loop_fails_closed` — reuse the existing `_Locked`/`_read` corruption contract (`ValueError`) and confirm the new multi-PR loop doesn't partially write before raising (concurrency/stale-state safety, extending the existing `test_a_corrupt_state_file_means_shadow_never_on_and_is_not_overwritten` coverage to the new code path).
10. `test_the_scan_states_its_measured_time_and_disk_cost` — with a fake `disk_ledger.du_kb` and a controlled clock, assert the scan's reported line/state includes the measured seconds and KB used (AC4, "verified not assumed": a real number, not a doc claim).

## Task List

1. Add `error_log.record(...)` wiring into the scoring orchestration's exception handler in `lib/auto_merge_shadow.py`, replacing the bare `stderr` print (keep the print too, for interactive visibility).
2. Refactor the single-PR `_score_one` call in `run()` into a bounded loop that scores multiple unscored PRs up to the chosen scan-level time budget (Decision `scan_budget`), still oldest-first via the existing `pick_unscored`.
3. Measure and report real cost per scan: wall-clock elapsed via `time.time()`, disk via `disk_ledger.du_kb(scratch, timeout=...)` on the scratch worktree right before it's removed; include both in the `step(...)` line `ticket_pipeline._auto_merge_shadow` already emits and in the persisted `last_report`.
4. Add a reason-classifier for "why is this PR still unscored" (queued-behind-N, mutation check unavailable, repeated failure from `error_log`), used only once a PR has been open > 24h without any score section.
5. Add the idempotent stated-reason action (Decision `stated_reason_channel`): post one PR comment (or set one shadow-state flag, per the decision), guarded so it never repeats for the same PR/cause.
6. Write the tests above first (`lib/tests/test_auto_merge_shadow.py`), confirm they fail against current code, then make them pass with steps 1–5.
7. Run the real stated-reason pass once against the live backlog (the 21 currently-pending PRs on `G-Eskayo/marvin`) so AC1's "write the cause into the PR" is satisfied for the existing backlog, not just future PRs.
8. Document the measured space/time cost per scan in `lib/auto_merge_shadow.py`'s module docstring and in `CONTEXT.md`'s Auto-merge section (§ designed 2026-10-09, ADR 0064), replacing the vague "each check can take 10 minutes" line with the concrete, decided budget.
9. Full test suite + the new tests green; confirm `graphify update .` after the code changes.