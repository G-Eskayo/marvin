## North-star fit

**Reuses**: `_missing()` (`skills/improve/scripts/daily_digest.py:45-46`) and the loud/quiet convention it encodes (ADR 0067 / CONTEXT.md "Endpoints and the brief" area) — already fully applied to both `bench_summary()` and `reviewer_health_summary()` in the current worktree. No new helper, no new pattern.

**Verified against the live files, not the prior design doc's claims**: the uncommitted `daily_digest.py` already has every fix the ticket asks for — `RESULTS_MD` points at `~/.agents/bench/RESULTS.md` (line 27), the reviewer-log guard at lines 157-158 correctly distinguishes "malformed/no markers" (loud) from "well-formed, empty in-window" (quiet), and the split regex at line 160 is correct. Running the full suite now (`~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_daily_digest.py -v`) gives **22/22 passed**. So the implementation is done; only one test is wrong, exactly the must-fix code review found: `test_main_short_circuits_when_out_file_exists` (`test_daily_digest.py:287-308`) only monkeypatches `roadmap_summary` with a call-tracking stub. `bench_summary`, `reviewer_health_summary`, and `call_claude` stay live. The test currently passes only because the short-circuit *happens* to work — if `main()`'s `OUT_FILE.exists()` check ever moved after any of those calls, this test would not just silently miss the regression, it would attempt a real `marvin_launcher.launch()` agentic call under pytest. That's the defect: a guard test that doesn't actually enforce the guard it claims to test. Fixing it doesn't require restructuring `main()` — only making the test's mocks match what the design doc itself already promised (task 7 / case 15).

**Simplest sufficient approach**: one test edit — swap the single call-tracking stub for four raise-on-call sentinels (`roadmap_summary`, `bench_summary`, `reviewer_health_summary`, `call_claude`), and assert `main()` returns without raising and without touching the pre-existing file content. No change to `daily_digest.py` itself is needed; the bug is entirely in the test.

**Tokens**: zero new LLM calls — this is a test-only fix. It directly removes a path by which a future regression would burn a real model call (and send a real desktop notification) inside a CI/test run instead of failing fast.

**Capability, not passivity**: a developer who breaks the short-circuit later gets an immediate, local, in-process test failure naming which function fired, instead of a slow/flaky test that occasionally phones out.

**Correcting the prior doc's own provenance claim**: the prior design doc called `test_daily_digest.py` an "existing file" with most tests "kept unchanged." `git status` shows it as untracked (`??`) — it is a new file in this diff, in full, not an edit to a pre-existing one. This revision states that accurately.

**Not touched (deferred, with reasoning, same as before)**:
- `daily_digest.py:147` (loud message on missing/fresh reviewer log) — intended behavior per the loud/quiet convention; a fresh machine correctly shows "missing" once until the first background-reviewer run, consistent with ADR 0067's "fail loudly" rule, not a defect.
- The two separate regex definitions of the run marker (`daily_digest.py:157` guard vs. `160` split lookahead) — real duplication risk, but consolidating touches the already-passing classification suite for a benefit the acceptance criteria don't require; better raised as an `architecture-review` backlog item than mixed into this fix.
- `test_reviewer_health_many_failures_truncated_to_5`'s `assert len(failure_lines) <= 5` (line 247) — true that it'd pass vacuously at 0 lines, but since I'm already in this file for the must-fix test, tightening it to `== 5` is a one-character, zero-risk strengthening directly in the spirit of "tests try to break it." Included below as a small addition, not scope creep on the must-fix.

## Tests to write first (all in `skills/improve/scripts/tests/test_daily_digest.py`)

The 21 other tests already cover every case in the ticket's "How we'll try to break it" list (bench file missing/empty/huge/malformed via `OSError`; reviewer log with 0/1/many runs, runs older than 7 days, malformed headers, no trailing newline, invalid timestamps) and all currently pass — unchanged. Only one test changes, plus one trivial strengthening:

1. **Rewrite `test_main_short_circuits_when_out_file_exists`** (closes the must-fix): replace the single `roadmap_summary` call-tracking mock with four sentinels — `roadmap_summary`, `bench_summary`, `reviewer_health_summary`, `call_claude` — each raising `AssertionError(f"{name} must not be called when short-circuiting")` if invoked. Assert `dd.main()` returns without raising, the pre-existing `out_file` content is byte-identical afterward, and the short-circuit message appears in stdout (`capsys`). This is the test that would have caught the original defect: with the old mock, swapping the order of `OUT_FILE.exists()` and `bench_summary()`/`call_claude()` in `main()` would pass silently; with the sentinels, it fails immediately with a clear name of which function fired early, before any live agent/notification call could happen.
2. **Tighten `test_reviewer_health_many_failures_truncated_to_5`**: change `assert len(failure_lines) <= 5` to `assert len(failure_lines) == 5`, so the test actually requires truncation to have happened rather than passing vacuously if the failure-detail bullets ever vanished.

No misuse case beyond the ticket's list needs a new code path: `reviewer_health_summary()` and `bench_summary()` are pure, single-process, stateless functions — concurrency, repeats, and stale state don't apply; the `OSError` tests already cover wrong-permissions.

## Decisions

None. This is a test-only correction of a previously-flagged defect; there is no design option for the owner to choose between.

## Task List

1. In `skills/improve/scripts/tests/test_daily_digest.py`, rewrite `test_main_short_circuits_when_out_file_exists`: replace the `roadmap_summary`-only call-tracking mock with raise-on-call sentinels patched onto `roadmap_summary`, `bench_summary`, `reviewer_health_summary`, and `call_claude`; assert `main()` returns cleanly, `out_file`'s content is unchanged, and the short-circuit message is printed.
2. In the same file, change `test_reviewer_health_many_failures_truncated_to_5`'s assertion from `assert len(failure_lines) <= 5` to `assert len(failure_lines) == 5`.
3. Run `~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_daily_digest.py -v` and confirm all 22 tests pass, with no test exercising `call_claude()`, `marvin_launcher.launch()`, or `notify()` live.
4. No change to `skills/improve/scripts/daily_digest.py` — it already satisfies every acceptance criterion; re-verify by re-reading the three touched functions (`bench_summary`, `reviewer_health_summary`, `main`) once more immediately before committing, to confirm nothing drifted between this plan and execution.