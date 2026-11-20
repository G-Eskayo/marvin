## North-star fit

**Reuses, rather than invents:**
- Cross-host parking already runs through the shared GitHub comment thread (`run_ticket._consecutive_failure_streak`/`_trailing_streaks`, `run_ticket.py:96-139`) — that path is already host-agnostic (box builds settle through `run_ticket.settle()` too, `box_build.py:437-438`). The bug isn't "box runs aren't counted," it's that failures (`FAILURE_MARKER`) and timeouts (`TIMEOUT_MARKER`) are tracked as two separate counters with two separate caps (3 vs 5, `run_ticket.py:39-40`), so a ticket that alternates failure/timeout outcomes across hosts never climbs either counter to its cap. Fix: one counter, one cap, reusing the same comment-thread mechanism — no new cross-host state store.
- ADR 0084 (`docs/adr/0084-an-unchanged-reading-passes-on-a-real-change.md`) already established "a test already red on the base doesn't block the build" for the *fully-unchanged* case. This ticket extends the same idea to the *partially-regressed* case, via `sandbox_orchestration._with_real_change` (`sandbox_orchestration.py:609-627`) and `metrics_registry.compare` (`metrics_registry.py:150-188`) — same compare() interface, no new verdict machinery.
- `outside_state.py` (`marvin#1047`) already exists for exactly "host-only checks" and is already wired into `main_health.py:48-59`. It is simply not wired into the ticket-build measure path (`build_type_measure.py`), which is the actual gap behind acceptance #4.
- `box_runner.failing_tests()` (`box_runner.py:83-86`) already extracts individual failing-test identities from pytest output via a short-summary regex — reused rather than re-invented for the identity-aware comparison acceptance #2 needs.
- The "sharpen or split" follow-up reuses `ticket_promotion.py`'s model-writes/code-publishes hook pattern (`ticket_promotion.py:1-40`) and the `to-issues` skill's tracer-bullet, ≤300-line slicing heuristic (`skills/to-issues/SKILL.md`), rather than inventing a new ticket-rewrite mechanism.

**Simplest sufficient approach:** every fix lives at the existing choke point for its concern (one counter in `run_ticket.settle`, one extra reconciliation step in `PairedMeasure`, one additive key in `capture_test_results`, one new narrow module for sharpen/split) — no new config file, no new per-machine state store, no new cross-host protocol.

**Tokens:** spends a little (one extra flagship-model call for sharpen/split, only on review-failure parks — rare) to save a lot (the ~130 wasted build rounds/2 days this ticket exists to stop).

**Phone-OS fit:** indirect — a pipeline that stops burning build hours on dead tickets is what lets MARVIN build more of itself.

**More capable, not more passive:** parking is still a hand-off to Gil with the real cause (unchanged); the sharpen/split step removes *busywork* (re-reading the same stale findings every parked ticket), not judgment.

## Decisions for the owner

One real architectural fork, not guessed:

```markdown
## Decisions
<!-- marvin:decisions -->
### red-base: How should the paired measure treat a test that disagrees between the base and current reading?
- [ ] A: Drop any test that fails on the base reading from the failed count on both sides (cheap; matches ADR 0084's existing "already red" language; only protects the direction where the flake hits the base reading)
- [ ] B: Re-run just the discordant tests (fail on exactly one side) once more; trust the result only if it reproduces, otherwise drop that test from both sides (catches flakiness in either direction; costs one extra narrow re-run, only when something disagrees)
- [ ] C: Both — B, plus skip a test from both sides outright if it's already red on a fresh pull of origin/main (the persistent, not-caused-by-this-change case) before even trying to reconcile it
```

I build **Option B** by default below (it's strictly more correct than A and bounded in cost — the test fails on both sides as a rare exception, not the common path), but the task list below implements it so the owner's answer can swap the reconciliation function without touching the call sites.

## Tests I'll write first

**Acceptance #1 — repeat cap (`lib/tests/test_run_ticket.py`, replacing the current streak tests):**
1. A ticket with exactly `MAX_FAILURES_IN_WINDOW - 1` (1) prior non-passing comments in the last 72h is released, not parked, on the next failure.
2. A ticket with `MAX_FAILURES_IN_WINDOW` (2) prior non-passing comments in the last 72h is parked on the next one.
3. **The exact reported bug:** a box-run `TIMEOUT_MARKER` comment followed by a Mac-run `FAILURE_MARKER` comment (different outcome kinds, different hosts) still parks at 2 — today's regression test for the real cross-counter gap.
4. A comment older than 72h is excluded from the count (a ticket that failed twice 4 days ago and once just now is not parked yet).
5. A `MODEL_MARKER` comment in between two failures is skipped (doesn't count, doesn't reset) — existing behavior, must still hold.
6. A person's comment resets the count to zero (existing behavior, must still hold).
7. A `HANDOFF_MARKER`/passed comment ends the trailing scan the same way.
8. `_issue_comments` returning `None` (gh unreadable) → treated as zero prior failures (fail open, never park on missing data) — existing behavior, must still hold.
9. A comment with a missing/malformed `createdAt` is still counted (fails toward "stop the runaway," not toward "silently loop forever").
10. Malformed/garbage comment bodies (`None`, non-dict entries, huge body text) don't crash the counter.
11. Concurrency: two hosts settling the *same* ticket number at nearly the same time (both read the same comment list before either posts) — document/assert the existing at-least-once race is unchanged (not solved by this ticket; GitHub's own comment ordering is the only serialization point) so nobody assumes this ticket silently fixed a different race.

**Acceptance #2 — comparison noise (`lib/tests/test_build_type_measure.py`, new):**
12. A test that fails identically on base and current contributes nothing to the verdict (sanity check: already true today via plain counts, must stay true).
13. A test that fails on current only, and reproduces on re-run → counted as a real regression (verdict stays "regressed"/"mixed" as appropriate).
14. A test that fails on base only, and reproduces on re-run → counted as a real fix.
15. **The flaky case:** a test that fails on current only on the first reading but passes on both sides on the re-run → excluded from both counts, so a genuine unrelated improvement elsewhere doesn't get drowned into "mixed".
16. Two discordant tests at once, one real, one flaky — each resolved independently.
17. The re-run step itself times out or the detached base worktree can't be created (`MeasureError`/`TestTimedOut`) → propagates, never silently swallowed into a wrong count.
18. Huge discordant set (every test in the selection disagrees) — re-run still runs each once, not quadratically; bounded cost asserted.

**Acceptance #4 — host-only checks (`lib/tests/test_evidence_capture.py`, new section):**
19. `capture_test_results` subtracts `outside_state`-marked failures from `passed`/`failed`/`total`, using a real `OUTSIDE STATE FAILED` line in captured output (not a mock of `outside_state.parse`).
20. A run with *only* outside-state failures reads as a clean pass for ticket-build purposes (mirrors `main_health.verdict`'s existing rule, `main_health.py:48-59`).
21. A run with one outside-state failure and one real failure still reports the real failure.
22. `outside_state.parse` finding nothing (no marked tests ran, or none failed) leaves counts untouched — no accidental off-by-one.
23. The excluded test ids never appear in `failed_tests` used by acceptance #2's reconciliation (so they can't be "discordant" either).

**Acceptance #3 — the flaky `test_dispatch_fallback` test:**
24. `test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` passes 20 times in a row run with `-n 6` (the acceptance criterion itself, run as a CI/local loop, not a unit test per se).
25. The loosened timing bound still *fails* if the wrapper actually waits for its 30s job (regression guard: assert the new threshold is still far below the job's own sleep duration, so the test keeps its teeth).

**Acceptance #5 — sharpen-or-split follow-up (`lib/tests/test_ticket_sharpen.py`, new):**
26. A park with non-empty `findings` triggers exactly one sharpen-or-split model call; a park with empty findings (timeout/mixed with no review findings) does not.
27. The model choosing "sharpen" rewrites the ticket body and flips `needs-info` → `ready-for-agent`; records which action was taken as a comment.
28. The model choosing "split" creates sub-issues (reusing `ticket_promotion`'s create hook), closes or relabels the original, and records which action was taken.
29. The model call failing/timing out never leaves the ticket silently stuck in `needs-info` with no trace — falls back to the existing plain park comment.
30. Called twice on the same park (duplicate trigger, two Macs racing) is idempotent — doesn't double-sharpen or double-split.

## Task List

1. **Unify the repeat cap across hosts** (`lib/run_ticket.py`): replace `MAX_CONSECUTIVE_FAILURES`/`MAX_CONSECUTIVE_RETRIES` and `_consecutive_failure_streak`/`_trailing_streaks` with one `MAX_FAILURES_IN_WINDOW = 2`, `FAILURE_WINDOW_HOURS = 72`, and one `_recent_failures(issue_number, repo=REPO, now=None, window_hours=FAILURE_WINDOW_HOURS) -> int` that walks comments newest-first, skips `MODEL_MARKER`, stops on a person/passed/handoff comment, stops once a comment's `createdAt` (parsed via `ticket_policy._parse`) falls outside the window, and counts every `FAILURE_MARKER`/`TIMEOUT_MARKER` comment it passes. Update both call sites in `settle()` to use the one counter and one threshold. Update the park headline text ("N in a row" → "N in the last 72h").
2. Update/replace the existing streak tests in `lib/tests/test_run_ticket.py` (items 1–11 above), including every existing `rt.MAX_CONSECUTIVE_FAILURES`/`rt._consecutive_failure_streak`/`rt._trailing_streaks` reference.
3. **Identity-aware test comparison** (`lib/evidence_capture.py`): add `failing_test_ids(output) -> set[str]` (the regex currently in `box_runner.FAILED_LINE`/`failing_tests`, moved here as the shared pure-parsing home); refactor `box_runner.failing_tests` to delegate to it. In `capture_test_results`, compute `failing_test_ids` and `outside_state.parse(output)` from the **full** output before truncating to `output_tail`; subtract outside-state failures from `passed`/`failed`/`total`; add `parsed["failed_tests"]` (ids, outside-state ones excluded) and `parsed["outside_state_failed"]`.
4. **Wire outside-state exclusion into ticket builds** (`lib/build_type_measure.py`): no code change needed beyond step 3 for `measure()`'s simple callers — verify `_suite_reading`/`measure()` naturally pick up the adjusted counts; add tests (items 19–23).
5. **Reconcile discordant tests** (`lib/build_type_measure.py::PairedMeasure`): extend `_pytest`/`_pytest_at_base` to also return `failed_tests` (3-tuple). In `__call__`, after computing `after`/`base` pytest readings, call a new `_reconcile(wt, base_ids, after_ids) -> (base_failed_adj, after_failed_adj)` implementing **Option B**: re-run the symmetric-difference tests once on each side (via the existing `_pytest`/`_pytest_at_base` with that small selection); drop a test from both counts if the re-run disagrees with the first reading on either side; otherwise trust the original reading. Feed the adjusted counts into `_metrics()`. Add tests (items 12–18).
6. **Fix the flaky dispatch-fallback test** (`lib/tests/test_dispatch_fallback.py:454`): loosen `assert time.monotonic() - t < 2` to a bound with real margin under `-n 6` contention (e.g. `< 10`, still a fifth of the 30s job it must not have waited for); add the regression guard (item 25). Run the test 20x under `-n 6` locally to confirm item 24 before considering this done.
7. **Sharpen-or-split module** (new `lib/ticket_sharpen.py`): `sharpen_or_split(issue_number, repo, findings, body, launch=None) -> dict`, triggered from `run_ticket._park_stuck_ticket` only when `findings` is non-empty. One flagship-model call (reusing `marvin_launcher.launch`/the `_launch` pattern from `sandbox_orchestration.py`) given the ticket body + findings, instructed to either rewrite the body with the missing contract or produce ≤300-line sub-ticket bodies (reusing `ticket_promotion`'s create-ticket hook and the `to-issues` slicing heuristic). On success: edit the ticket body (sharpen) or create sub-issues and close/relabel the original (split), flip `needs-info` → `ready-for-agent`, comment which action was taken. On failure: leave the plain park comment as today (no new stuck state). Idempotency guard: skip if a "Sharpened"/"Split into" marker comment already exists on this park.
8. Add `lib/tests/test_ticket_sharpen.py` (items 26–30).
9. **Record the design decision**: amend `docs/adr/0084-an-unchanged-reading-passes-on-a-real-change.md` (or add a short new ADR) documenting the discordant-test reconciliation rule chosen from the Decisions block, once answered.
10. Run the full `lib/tests` suite plus the dashboard suite locally before raising the PR (per "Full suites before a hand-merge" convention); confirm no regression in `test_main_health.py`, `test_box_build.py`, `test_outside_state.py`, or `test_metrics_registry.py` (none of which this ticket should touch behaviorally, only `run_ticket`, `build_type_measure`, `evidence_capture`, `box_runner`, `test_dispatch_fallback`, and the new `ticket_sharpen`).