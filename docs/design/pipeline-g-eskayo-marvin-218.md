Good, that part's consistent. I now have a complete diagnosis of the prior attempt's defects. Here's the revised plan.

## North-star fit

**Reuses** (unchanged from the prior attempt's correct calls, verified against the code now sitting in this worktree): `failure_breaker.py`'s append-only `pipeline-failures.jsonl` log (`LOG_PATH`, `record_failure`/`record_success` already called at `lib/run_ticket.py:354,385,399`) — no new state store, satisfying AC #1. The `hold`/`Revisit by:` convention from #213 (`ticket_policy.parse_revisit_comment`/`latest_revisit`/`is_revisit_due`, the `revisit` ticket agent, `health_checks.check_hold_revisit`) so a ticket held by this rule is picked up by the existing revisit flow with zero changes there. `project_profile._validate()`'s per-field-default-and-validate pattern. `health_checks.check_missing_profiles`'s injectable `(snapshot=None, repos=None, gh=None)` pattern, already followed by the new `check_retry_storm_holds`. The suite-wide `conftest.py:109-113` autouse fixture that redirects `failure_breaker.LOG_PATH` to a tmp file for every test — already in place, already correct, no new isolation machinery needed.

**Simplest sufficient approach, corrected:** the shape of the prior attempt (two pure functions in `failure_breaker.py`, one validated profile field, one `STATE_LABELS` fix, one `format_revisit` helper, one new Health check, one branch in `run()`) is right and I am keeping it. What's wrong is in the *implementation details*, not the design — see below.

**Token/cost:** unchanged — this is the token-saving change itself (retry storms were ~70% of output tokens), pure log-reading, zero model calls.

**More capable, not more passive:** unchanged — a human stops being paged by an endlessly-retrying ticket, sees one clear hold reason instead, and can still force a re-run by hand.

## Why the last attempt regressed 5 tests (root-caused, not guessed)

I ran `pytest lib/tests/test_run_ticket.py lib/tests/test_failure_breaker.py lib/tests/test_project_profile.py lib/tests/test_ticket_policy.py lib/tests/test_health_checks.py` against the code already sitting uncommitted in this worktree (left by the previous attempt) and reproduced exactly the 5 reported failures, all in `test_run_ticket.py`. Two distinct bugs:

**Bug A — the hold decision bypasses the existing test seam (3 of 5 failures).** `run_ticket.py:383-392` now does:
```python
prior_streak = _consecutive_failure_streak(issue_number, **kw)   # mockable seam
...
hold_data = failure_breaker.should_hold(issue_number, project=repo, threshold=threshold)  # re-reads the log directly
parking = hold_data is not None
```
`should_hold` re-derives the count from the (test-isolated, but otherwise *real*) jsonl log — it ignores `prior_streak` entirely. ~20 existing tests (and the 3 failing ones: `test_run_parks_the_ticket_instead_of_releasing_at_the_failure_cap`, `test_run_passes_the_cause_and_the_last_must_fix_findings_to_park`, `test_a_crash_before_any_result_still_parks_with_the_crash_as_the_cause`) monkeypatch `_consecutive_failure_streak` to force a specific streak and expect that alone to decide parking. Since the isolated-log fixture starts every test with an empty log, `should_hold` sees 0 real failures and always returns `None`, so parking never happens no matter what the seam is mocked to — `_park_stuck_ticket` is never called, and `got["reason"]`/`got` stay empty. **Fix:** keep the count-based decision routed entirely through `_consecutive_failure_streak`'s return value (`new_count = prior_streak + 1 >= threshold`), and make the repeat-signature check an independent, additive condition read from the log via a small new helper — not a second call that recomputes (and overrides) the count.

**Bug B — 2 of the 5 failures are obsolete tests, not implementation bugs.** `test_consecutive_failure_streak_counts_trailing_failure_comments` and `test_consecutive_failure_streak_resets_on_a_human_comment` test the *old* contract of `_consecutive_failure_streak` (count trailing GH-issue comments). AC #1 explicitly requires the new contract (count from `pipeline-failures.jsonl`), so this function's behavior change is correct and required — these two tests are now testing removed behavior and must be deleted and replaced with jsonl-based equivalents. The prior attempt changed the function but never touched these tests — exactly the "verify fails when code changes without a test changing" case this ticket is checked against.

**Three more defects found by reading the already-written code (not yet causing a visible test failure, because no test exercises them — closing this gap is why the tests-first list below is longer than the prior attempt's):**

- `failure_breaker.should_hold`: `threshold = max(3, int(threshold) if threshold else 3)` floors *every* threshold to at least 3 — a profile with `failure_threshold: 1` or `2` (a valid, positive int per `project_profile`'s own validation) can never actually hold at 1 or 2. Only *non-positive/non-numeric* input should clamp to a default; a valid lower override must be honored.
- `failure_breaker.ticket_streak`: direct `r["ticket"]`, `r["kind"]`, `r["sig"]` indexing (no `.get()`) will `KeyError` on a record from an older schema or a corrupted line that `_read()`'s existing guard didn't fully normalize; and the "since the last success" slice uses `mine.index(r) > last_success_idx`, which is O(n²) and, worse, resolves to the *first* positionally-equal record when two failure records are byte-identical dicts (same ticket/project/sig/reason/timestamp) — picking the wrong index. Needs `enumerate()` and defensive `.get()` throughout.
- `project_profile._validate`: `ft_int = int(ft)` silently truncates a float (`2.5` → `2`, accepted) and silently parses a numeric string (`"3"` → `3`, accepted) — the ticket's own test list calls for both to raise `ValueError`. Needs `isinstance(ft, int) and not isinstance(ft, bool)` before any numeric check.
- **No test coverage was added at all** for `health_checks.check_retry_storm_holds` (new function, zero tests) or for `run_ticket._park_stuck_ticket`'s new `hold_data` branch (comment format, label, the revisit line) — the exact gap the metrics check is designed to catch.

## Decisions for the owner

<!-- marvin:decisions -->
### revisit_days: How many days before a held ticket is revisited?
- [ ] A: 7 days
- [ ] B: 14 days
- [ ] C: 30 days

(Unchanged from the prior attempt — still unanswered across every retry so far; defaulting to **B: 14 days** as `DEFAULT_REVISIT_DAYS` if this ships before an answer lands, since the worktree's current code already uses 7 and 14 inconsistently across attempts and the ticket gives no signal either way.)

## Tests to write FIRST

No "How we'll try to break it" section exists on this ticket. Deriving the list from AC #4 plus the standard misuse checklist, and extending the prior attempt's list with the coverage gaps found above:

**`lib/tests/test_failure_breaker.py`** (the 11 already in the worktree are correctly shaped and pass — keep them; add):
1. A custom `failure_threshold` **below** 3 (e.g. `threshold=1`) trips on the first failure — closes the `max(3, ...)` floor bug, the one gap none of the existing 11 tests catch.
2. A corrupt/malformed log line (missing `"ticket"` or `"kind"` key, or a line that isn't valid JSON) never crashes `ticket_streak` — `_read()`'s guard plus defensive `.get()` inside the ticket-scoped loop.
3. Two byte-identical failure records (same ticket/project/sig/reason/timestamp) for the same ticket are both counted once each, not de-duplicated or mis-ordered by the "since last success" slice (regression guard for the `mine.index(r)` bug).
4. A huge number of failure records for one ticket (hundreds) completes in bounded time (misuse: huge input / replay).
5. Empty log / no record for this ticket → `count=0`, `should_hold` → `None` (misuse: empty input).
6. Two identical signatures that are *not* adjacent (a different failure in between) does **not** trip the repeat-signature condition — only genuinely consecutive matches do.

**`lib/tests/test_project_profile.py`** (extend the one test already there):
7. `failure_threshold` set to a float (`2.5`) or a numeric string (`"3"`) → `ValueError` naming the field (currently silently accepted — real bug, not yet covered).

**`lib/tests/test_ticket_policy.py`** (the 2 already there are fine — add):
8. `format_revisit` with a `condition` string containing `—`, `--`, or a newline does not break `parse_revisit_comment`'s regex round-trip (misuse: a condition string that collides with the format's own separator).

**`lib/tests/test_run_ticket.py`** (none were added by the prior attempt — this is the actual cause of the regression; write all of these before touching `run_ticket.py`):
9. Rewrite `test_run_parks_the_ticket_instead_of_releasing_at_the_failure_cap` so mocking `_consecutive_failure_streak` to `MAX_CONSECUTIVE_FAILURES - 1` still determines parking after the jsonl-based rewrite (this is the regression test for Bug A — must fail against the current worktree code, pass after the fix).
10. Delete `test_consecutive_failure_streak_counts_trailing_failure_comments` and `test_consecutive_failure_streak_resets_on_a_human_comment` (obsolete contract) and replace with: `_consecutive_failure_streak` delegates to `failure_breaker.ticket_streak(...)["count"]` — one test seeding the isolated log directly and asserting the returned int matches.
11. At threshold: `_park_stuck_ticket` is called with `hold_data` set and label `hold` (not `needs-info`).
12. Below threshold, no repeat signature: unchanged behavior — release + retry comment, no park.
13. A repeat identical signature trips parking even when the raw count is below `failure_threshold` (reuses `failure_breaker`'s real repeat-signature check against the isolated log, not a mock — this is the "real collaborator over a mock" case, since mocking the condition away would hide exactly the bug just found).
14. `_park_stuck_ticket(..., hold_data=None)` (the existing timeout and too-vague callers) is byte-identical to current behavior — regression guard.
15. `_park_stuck_ticket(..., hold_data={...})`: comment contains the failure signatures (truncated) and a bare `Revisit by: YYYY-MM-DD — <condition>` line on its own line.
16. A profile with `failure_threshold` set overrides `MAX_CONSECUTIVE_FAILURES`; no profile or `failure_threshold: None` falls back to it.
17. A failing `gh issue edit`/`gh issue comment` call during the hold-park never crashes the run (dependency failing), mirroring the existing pattern for the `needs-info` path.
18. Two `run()` calls racing on the same ticket (concurrency): both append to the isolated jsonl; the second sees the first's failure already logged and computes a higher count — no lost update.

**`lib/tests/test_health_checks.py`** (none exist for the new function — add, mirroring `check_missing_profiles`'s tests):
19. No held tickets anywhere → green, `value=0`.
20. A `hold`-labeled ticket with `ticket_streak(...).count == 0` (held by a person, not this rule) → excluded.
21. A ticket held by this rule → yellow, named, truncated at 5+.
22. `gh`/snapshot collection failing for one repo never stops the others.
23. Injected `repos=[]`/`gh=` skips the live `gh issue list` call entirely (test isolation parity).

## Task List

1. **`lib/failure_breaker.py`** — fix the two defects found: (a) `should_hold`'s threshold clamp so only non-positive/non-numeric input falls back to a default, a valid positive override of any size (including below 3) is honored; (b) `ticket_streak`'s "since last success" slice uses `enumerate()` with defensive `.get()` on every field read inside the ticket-scoped loop, never raw indexing. Write tests 1–6 first.
2. **`lib/project_profile.py`** — tighten `_validate()`'s `failure_threshold` check to `isinstance(ft, int) and not isinstance(ft, bool)` before the positivity check, rejecting floats and numeric strings. Write test 7 first.
3. **`lib/ticket_policy.py`** — no code change needed (`"hold"` in `STATE_LABELS` and `format_revisit` are already correct and tested); write test 8 first to confirm the separator-collision edge case, fix `format_revisit`/`parse_revisit_comment` only if it fails.
4. **`lib/run_ticket.py`** — fix Bug A: restructure the generic-failure branch so the count-based threshold check stays routed through `_consecutive_failure_streak`'s return value (`new_count = prior_streak + 1; parking = new_count >= threshold or repeat_signature`), where `repeat_signature` is a small additional read (e.g. `failure_breaker.ticket_streak(...)["signatures"]`'s last two entries) that *adds* to, but never replaces, the seam-controlled count. Construct `hold_data` from `new_count`/`threshold`/the repeat check locally in `run_ticket.py` rather than calling `failure_breaker.should_hold()` a second time against the live log. Write tests 9, 11–18 first (9 must fail against the current worktree code before the fix, confirming it's a real regression test).
5. **`lib/tests/test_run_ticket.py`** — delete the 2 obsolete comment-based `_consecutive_failure_streak` tests and replace per test 10, before step 4's rewrite lands.
6. **`lib/health_checks.py`** — no code change expected (the existing `check_retry_storm_holds` matches the reused pattern); write tests 19–23 first against it, fix only what they catch.
7. **`CONTEXT.md`** — already documents the mechanism correctly; update only the revisit-days value once the Decision above resolves (currently inconsistent between 7 and 14 across attempts — pick the Decision's answer, or 14 if it ships unanswered).
8. Run `pytest lib/tests/` (full suite) and confirm the previously-failing 5 now pass with no new regressions elsewhere, then `npx vitest run` in `dashboard/` as a sanity pass (no JS touched).