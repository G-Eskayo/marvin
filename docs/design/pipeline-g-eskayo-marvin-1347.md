No decisions conflict with this fix. Now let me write the plan.

## North-star fit

**Reuses:** the existing injectable-clock pattern already used throughout `lib/stale_relay.py` — `week(now=...)`, `row(..., now=...)`, and the test's own `ts(days_ago)` helper (`lib/tests/test_stale_relay.py:35-36`) that derives timestamps relative to a frozen `NOW`. `question_log.add()` is the one function in this dependency chain with no such hook — every other time-sensitive function already takes an injectable clock. Adding a keyword-only `ts` override to `add()` (default `None` → real wall clock, unchanged for every production caller) extends the same pattern rather than inventing a new one.

**Simplest sufficient approach:** the regression is a single root cause — `test_a_week_counts_caught_and_both_kinds_of_leaked` (`lib/tests/test_stale_relay.py:91-103`) calls `ql.add(..., kind="stale", path=env["question_log"])` with no time control, so the row gets stamped with the *real* `datetime.now(timezone.utc)` (`lib/question_log.py:49`), while `sr.week()` is called with a frozen `now=NOW` where `NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)` (`lib/tests/test_stale_relay.py:32,57-58`). The test passed only while the CI run's real wall-clock time was before 2026-11-16 12:00 UTC; today's run executed at 16:42 UTC — after that cutoff — so the logged row's real timestamp falls outside `week()`'s `[cut, now]` window and `logged` comes back `0` instead of `1`. This is a ticking time bomb, not a one-off CI flake: it will fail on every run from now on. Fix: give `add()` an injectable `ts` (mirrors `week`'s `now`), and have the test pass `ts=ts(1)` so the logged row sits inside the fixed window deterministically, exactly like the resume-log rows and transcript corrections in the same test already do via `ts()`.

**Token/compute cost:** trivial — one new optional kwarg, one test-call update. No new files, no abstraction.

**Phone-OS direction:** neutral; this is a correctness fix to an existing freshness probe, not new capability.

**User capability:** restores main to green and keeps the stale-relay leak probe trustworthy (it's the one that proves corrections pieces #1221/#1224 work) — it leaves Gil with an accurate, non-flaky signal rather than one that silently breaks on a timer.

**Why not revert:** the fix is small (one kwarg + one call-site edit), so forward-fix per the ticket's own "revert only if a fix is not small" instruction.

## Tests to write first (TDD)

Per the ticket's "How we'll try to break it" + ADR 0063 adversarial coverage:

1. **The named failing test must pass deterministically regardless of wall-clock time.** Update `test_a_week_counts_caught_and_both_kinds_of_leaked` to call `ql.add("Why did you say #17 was urgent?", kind="stale", path=env["question_log"], ts=ts(1))`, keeping the existing assertions (`caught==3, logged==1, said==1, leaked==2`). This is the regression test — it must fail against current `question_log.py` (no `ts` kwarg → `TypeError`) and pass once `add()` supports it.
2. **A logged row outside the week window is excluded.** New case: `ql.add(..., kind="stale", path=..., ts=ts(9))` (9 days ago, matching the existing "outside the week" convention at line 96) must NOT be counted in `logged`.
3. **`ts` defaults to real wall-clock when omitted** (no regression for production callers / the CLI path): assert `ql.add("q", path=p)["ts"]` is close to `datetime.now(UTC)` (within a few seconds), so the new kwarg doesn't change default behavior.
4. **Malformed/garbled `ts` input doesn't crash `add`** — e.g. `ts="not-a-date"` or `ts=12345` — mirrors the existing robustness bar (`test_a_garbled_cache_or_log_never_raises`); either raise a clear `ValueError` or fall back to real time, but never let a bad caller corrupt the log silently with an unparseable row. (Decision below — this needs the owner's call.)
5. **Re-run `lib/tests/test_question_log.py` unchanged** to confirm the new optional kwarg doesn't disturb existing question_log behavior (empty question, oversized question, duplicate counting, injection payload as literal text, concurrent-write test at line 74) — no new test needed, just confirms no regression.
6. **Verify on a clean checkout**, per the ticket's own break-it step: after the fix, re-run `lib/tests/test_stale_relay.py -v` fresh (not reusing worktree state) and confirm `1 failed` → `0 failed`, with no test skipped/deleted to get there.

<!-- marvin:decisions -->
### ts-validation: how should `question_log.add(ts=...)` handle a malformed `ts`?
- [ ] Raise `ValueError` immediately (fail loud; keeps the log always well-formed, but a careless caller crashes rather than logging)
- [ ] Silently fall back to `datetime.now(timezone.utc)` if `ts` doesn't parse (log always gets a row, but a caller's bug is masked)

## Task List

1. Add `test_logged_row_outside_week_is_excluded` (or extend the existing test) to `lib/tests/test_stale_relay.py` asserting a `ts=ts(9)` stale-log row is not counted in `logged`.
2. Add a test asserting `add()`'s default `ts` (omitted) still stamps real wall-clock time, in `lib/tests/test_question_log.py`.
3. Add a test for malformed `ts` input per the Decision above (write it to match whichever option gets picked; default to the "raise ValueError" branch if the PR ships before an answer, and flag it as provisional).
4. Update `test_a_week_counts_caught_and_both_kinds_of_leaked` in `lib/tests/test_stale_relay.py:98` to pass `ts=ts(1)` to the `kind="stale"` call — the regression test; confirm it fails against current `lib/question_log.py`.
5. Add a keyword-only `ts: str | None = None` parameter to `question_log.add()` (`lib/question_log.py:42`): when given, use it (validated per the Decision) instead of `datetime.now(timezone.utc).isoformat(...)` for the row's `"ts"` field; default preserves current behavior exactly. Do not expose it via the CLI (`main()`/argparse) — it's a testability hook, not a user-facing flag.
6. Run the full `lib/tests/test_stale_relay.py` and `lib/tests/test_question_log.py` suites locally; confirm all pass.
7. Run the complete Python test suite (per the "Full suites before a hand-merge" rule) before opening the PR.
8. Open the PR referencing this ticket ("Closes #1347"), noting in the description that this was a forward fix (not a revert) because the change was one optional kwarg plus one call-site update.
9. After merge, confirm the CI run on main is green and the ticket self-closes.