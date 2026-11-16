1. **`lib/run_ticket.py` — bounded, cross-host park trigger**
   - Add `PARK_WINDOW_HOURS = 72` and change `MAX_CONSECUTIVE_FAILURES` default to `2`.
   - Extend `_issue_comments`'s callers (or add a small helper) to read each comment's `createdAt` (already present in `gh issue view --json comments`' default shape, just unused today).
   - Rework `_trailing_streaks`/`_consecutive_failure_streak` into a windowed count: still skip `MODEL_MARKER`/bot comments as today, still stop at a genuine person comment (handoff semantics unchanged), but count every qualifying failure/timeout comment whose `createdAt` is within `PARK_WINDOW_HOURS`, regardless of an intervening pass within that same window (tests 1-6).
   - Keep `MAX_CONSECUTIVE_RETRIES` (timeout cap) untouched — out of scope per the acceptance, which only names the review-failure cap.

2. **Tests for task 1** — extend `lib/tests/test_run_ticket.py` alongside the existing `test_consecutive_failure_streak_*` tests, covering cases 1-8.

3. **`lib/evidence_capture.py` — per-test failure identity**
   - Add a small additive function (e.g. `failed_test_ids(output: str) -> set[str]`) parsing pytest's "short test summary info" `FAILED <nodeid> - ...` lines. Existing `parse_test_output` return shape unchanged (no caller breakage).

4. **`lib/build_type_measure.py` — ignore red-on-base, re-run single-sided failures**
   - `_measure_commands()` and `PairedMeasure._pytest`/`_pytest_at_base`: add `-m "not outside_state"` to the pytest command (acceptance 4).
   - `PairedMeasure.__call__`: after computing `after`/`base` pytest readings, diff failed-test-id sets; for any id failed on `after` only, re-run just that id once; fold the result back into the counts handed to `_metrics()` per tests 9-14 (flake excluded, real regression kept, base-only fixes left neutral).

5. **Tests for tasks 3-4** — extend `lib/tests/test_evidence_capture.py` and `lib/tests/test_build_type_measure.py`, covering cases 9-14 and 17-19 (including the `main_health.py` non-regression check).

6. **`lib/tests/test_dispatch_fallback.py` — fix the flaky test outright**
   - Widen `p.wait(timeout=3)` → a larger bound, `time.monotonic() - t < 2` → a larger margin, and `_gone`'s default `seconds=3.0` → a larger default, all still comfortably under the real 30s bug the test guards against.
   - Verify: run the parametrized test 20× under `-n 6` (case 15) and confirm a deliberately-reintroduced "wrapper waits for its job" bug still fails it (case 16).

7. **Sharpen-or-split pass** (shape depends on the `split_mechanic` Decision)
   - New small module (e.g. `lib/ticket_sharpen.py`), modeled on `denial_diagnosis.classify()`: one `marvin_launcher.launch("background-analyst", ...)` call reading the ticket body + the park's `findings`, returning a structured `rewrite` or `split` verdict plus the new body / slice descriptions.
   - Wire it into `run_ticket._park_stuck_ticket`: when `findings` is non-empty, call it best-effort (try/except, bounded timeout) after posting the park comment.
   - Implement the chosen mechanic (A or B per the Decision above); either path ends with a "Record which it did on the ticket" comment (case 21/22), and the ticket only returns to `ready-for-agent` after this step (case 20), never left in a guessed/garbled state (case 23).

8. **Tests for task 7** — new `lib/tests/test_ticket_sharpen.py`, covering cases 20-25, modeled on `lib/tests/test_denial_diagnosis.py`'s existing patterns if present (check for one; if absent, model on `denial_diagnosis.py`'s own structure directly).

9. **Full local verification**: all of `lib/tests/` (Python) green, plus a manual 20× loop of the dispatch-fallback test under `-n 6`, before raising the PR — per `feedback-full-suites-before-hand-merge`.