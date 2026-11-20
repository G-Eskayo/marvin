## North-star fit

**Reuses, before adding anything:**
- `lib/run_ticket.py:_trailing_streaks`/`_consecutive_failure_streak`/`_park_stuck_ticket` (96–188) — the per-ticket streak-and-park mechanism already reads the **shared GitHub issue thread**, so it is already cross-host by construction (`lib/box_build.py:377–438` calls the identical `settle()` the Mac path calls). The gap is not "doesn't work across hosts," it's that it has **no time window** and defaults to N=3, not the N=2/72h the ticket asks for.
- `lib/outside_state.py` (ADR-backed, marvin#1047) — already solves "ignore tests that are red for reasons outside this repo's code" for CI/main-health (`lib/main_health.py:verdict()` 48–59). It is simply never called from the ticket-build comparison path (`lib/build_type_measure.py:measure()`/`PairedMeasure`), which is why main-health is already correctly green while ticket builds still see the same 7 tests as real failures.
- `lib/ticket_pipeline.py:_retry_not_before` (710–726) — the existing per-ticket, per-dispatch `gh issue view --json comments` call at the **one choke point both box and Mac dispatch share** (`_dispatch_one`, 1041). Extending this call (not adding a new one) is both the cheapest and the most robust place to enforce the cap, per [[feedback-catch-repeated-mistakes]] ("fix at the root, at the choke point") — it holds even if something downstream (triage, a label edit) ever re-opens a parked ticket.
- `lib/box_runner.py:FAILED_LINE`/`failing_tests` (50, 83–86) and `lib/main_health.py:failed_ids` (44–45) — two existing, near-duplicate per-test-name extractors; the fix converges on one rather than writing a third.
- `lib/health_checks.py`'s small-module `row()` registry pattern (used by `parked.row()`, `stale_relay.row()`) for the new "stale captured elements" health row.
- `lib/run_ticket.py:_park_stuck_ticket`'s comment/label mechanics (146–188) as the pattern the new "sharpen or split" step reuses for its own ticket edit/comment.

**Simplest sufficient approach:** every fix is a parameter change or a missing wire-up of an already-built mechanism (time window + lower default; call `outside_state.parse()` where it's already called for CI; fix one `importlib.util.find_spec` check to also check the browser binary; loosen two wall-clock assertions). The one genuinely new piece — "sharpen or split" — is scoped to firing only on review-failure parks, reusing the existing comment/label plumbing rather than inventing new state.

**Tokens:** spends nothing extra at steady state — the dispatch-time guard reuses a `gh` call already being made for `_retry_not_before`; the `outside_state` wiring runs on output the test command already produced. It *saves* tokens and machine-hours by cutting ~130 wasted build rounds down to ~2 failures × N tickets before a human is asked to unblock them, and the sharpen-or-split step spends one agent run only on tickets that actually reach the cap, not speculatively.

**Phone-OS direction:** indirect — a pipeline that stops burning build-hours on dead tickets is more of the "always-on, reliable, nothing breaks silently" substrate north star 2 depends on.

**More capable or more passive:** more capable — parked tickets now carry an automatic rewrite/split instead of sitting mute in Needs-you; the owner spends attention on genuinely ambiguous tickets, not on noticing a 2-day stall by hand.

---

## Decisions

Two points genuinely need the owner's call; everything else above is unambiguous enough to just build.

<!-- marvin:decisions -->
### flaky-fallback: Acceptance #2 names two fixes for a result reading "mixed" because of a test that's flaky or already red. Which should ship?
- [ ] A: Reuse `outside_state` only (recommended) — wire the existing `@pytest.mark.outside_state(...)` exclusion into `build_type_measure.py`, exactly as `main_health.py` already does for CI. Covers every test someone has *already marked* as environment-dependent (the 7 portfolio-parity tests today). Zero new machinery.
- [ ] B: A plus a generic "rerun the test that disagrees between base and current before trusting it" safety net in `PairedMeasure`, for tests nobody has marked yet. Catches future unmarked flakes automatically, at the cost of a second subprocess run whenever base and current disagree on any test.

### sharpen-timing: When should the new "sharpen or split" pass run after a review-failure park?
- [ ] A: Eagerly, right when `_park_stuck_ticket` posts the park comment — the ticket is immediately actionable, but it spends one agent run on every parked ticket even if a person closes or reprioritizes it first.
- [ ] B: Lazily — only when something next tries to dispatch a still-`needs-info` ticket and finds it was parked for review failures; skips the cost for tickets a person handles directly, at the cost of the rewrite not existing until the next dispatch attempt notices.

---

## Tests first

The ticket has no "How we'll try to break it" section, so these are built from its Acceptance criteria plus the adversarial cases ADR 0063 requires for anything touching dispatch state, GitHub comments, and concurrency. Written against the real collaborator (the GitHub issue thread, via a fake `gh` double matching `FakeGitHub`'s existing shape in `test_resume_check.py`, not a mock that could hide the comment-ordering rules) wherever a mock could hide those rules; real subprocess + real signals for the dispatch-fallback fix (no mocking the OS).

**Repeat cap (acceptance #1), extending `lib/tests/test_run_ticket.py` and `lib/tests/test_ticket_pipeline.py`:**
1. Two trailing failures within 72h park the ticket (new default N=2), where today's suite expects 3 — update/extend `test_run_parks_the_ticket_instead_of_releasing_at_the_failure_cap`.
2. A failure comment older than 72h does **not** count toward the cap, even if it's the most recent comment (clock-skew / stale-thread case).
3. **Box run followed by a Mac run**: a failure comment posted while claimed `mac-mini-2012` (box), then a failure comment posted while claimed as a Mac label, both within 72h — park fires on the 2nd, proving the cap is genuinely host-agnostic, not just host-agnostic in theory.
4. A park already recorded, then the ticket's `ready-for-agent` label somehow reappears (triage glitch, a hand-edit) — `_dispatch_one`'s new choke-point guard refuses to redispatch anyway, because the same comments still show 2 failures in the last 72h. (This is the "fix at the root" regression test — it must fail if someone removes the dispatch-time check and relies on labels alone.)
5. A park releases itself once the window passes — a 3rd attempt 73h after the first failure is allowed (the ticket "changes" by time, as acceptance #1 requires).
6. A person's comment between two failures resets the cap window the same way it resets the streak today (no regression on existing behavior).
7. Concurrent box + Mac dispatch race: two `gh issue view` reads of the same thread, interleaved with two `settle()` calls — the cap must not under- or double-count (idempotent on the shared thread, not on local state).
8. `gh` unreachable / malformed JSON mid-check — dispatch must fail open the same way `_retry_not_before` already does (never block the whole scan on one bad ticket).
9. The repeat-cap window constant and N are each independently overridable (so main-health or a future project can tune them without touching call sites) — a pure unit test on the new `ticket_policy` function.

**Comparison ignoring red-on-base (acceptance #2), extending `lib/tests/test_build_type_measure.py`:**
10. A test marked `outside_state` that fails on **both** base and current never appears in `tests_failed` on either side → verdict is `unchanged`, not `mixed` (the literal #1339 scenario).
11. A test marked `outside_state` that fails on current only (the thing just broke) is still excluded from the *ticket's* pass/fail metric, but is still visible somewhere (it must not become invisible — see check #15).
12. A **large number** of `outside_state` failures (7+) still all get extracted — regression test against the `output_tail` truncation risk found in `evidence_capture.capture_test_results` (the `OUTSIDE STATE FAILED` lines must be parsed from full output, before the 600-char tail truncation, not after).
13. An unmarked, genuinely new regression (not `outside_state`) is still caught — the exclusion must not swallow real regressions.
14. Malformed/missing `OUTSIDE STATE FAILED` lines (empty `what`, duplicate test id, output with no such lines at all) never crash `measure()`.
15. (If Decision flaky-fallback = B) a test that disagrees between the base and current reading is re-run once; if the re-run agrees with the majority, that direction wins; if it still disagrees, the original (conservative) verdict stands — tested with a fake runner returning different results on successive calls.

**`test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` (acceptance #3):**
16. The existing 3 parametrize cases (`sig,code` = (15,143), (2,130), (1,129)) pass individually (regression guard).
17. The acceptance's own bar: `pytest -n 6 lib/tests/test_dispatch_fallback.py -k signal_to_the_wrapper_alone --count 20` (or an equivalent 20-iteration shell loop if `pytest-repeat` isn't available) is green 20/20 — this *is* the acceptance test, run as part of verification, not a new assertion in the file.
18. A deliberately starved CPU (e.g. `os.sched_setaffinity` to 1 core, or a busy-loop fixture) still meets the loosened budget — a stand-in for "-n 6 contention" that doesn't depend on actually running 6 xdist workers to prove the fix.

**Host-only checks visibility (acceptance #4), extending `lib/tests/test_portfolio_parity.py` and a new `lib/tests/test_<new-health-module>.py`:**
19. `_has_playwright()` returns `False` when the module imports but the Chromium binary is absent (today's exact failure mode) — currently it returns `True` and the test crashes instead of skipping.
20. With the fixed check, a missing-chromium machine now **skips** cleanly with a `pytest.skip` reason, not an error.
21. The new main-health row for stale captures reports yellow with "stale since <date>, needs re-capture" when the 4 known-stale elements are the only outside_state failures, and reports differently (or stays silent) once they're re-captured.
22. That row never goes red regardless of how many elements are stale — a host-only/capture-drift problem is visibility, not a build-breaker (matches `parked.row()`'s "never green on a guess, never red on a skip" pattern).

**Sharpen-or-split follow-on:**
23. A park caused by review-failure findings triggers the sharpen-or-split pass exactly once; a park caused by `too_vague` or a verify timeout does **not** (the owner's comment scopes this to review-failure parks only).
24. The pass records on the ticket which action it took (rewrite vs. split) — idempotent: running it twice on the same park doesn't double-comment or re-split an already-split ticket.
25. A split ticket's resulting slices are each under ~300 lines of ticket body change description; a rewrite names the missing contract pieces the review findings actually pointed at (not a generic restatement).
26. The ticket only returns to `ready-for-agent` after this pass completes, never before — if the agent run itself fails/crashes, the ticket stays `needs-info` rather than silently reappearing in the queue unsharpened.

---

## Task List

1. **`ticket_policy.py`**: add `REPEAT_CAP_FAILURES = 2` and `REPEAT_CAP_WINDOW_H = 72` (next to `STALE_CLAIM_HOURS`/retry constants), plus a pure function `repeat_capped(comments, now) -> dict | None` that walks trailing automated comments the same way `run_ticket._trailing_streaks` does but stops counting (not just stops at a person's comment) once a comment's `createdAt` is older than the window, returning `{reason, streak}` or `None`. Covers tests 1, 2, 6, 9.
2. **`run_ticket.py`**: replace the direct `MAX_CONSECUTIVE_FAILURES`/unbounded `_trailing_streaks` lookback in `settle()` (413–420) with a call into the new `ticket_policy.repeat_capped`, keeping the existing timeout/model/vague branches untouched. Update `test_run_ticket.py`'s existing streak tests for the new default and window. Covers tests 1, 2, 3, 5, 6.
3. **`ticket_pipeline.py`**: add a second, independent gate inside `_dispatch_one` (1041), right alongside `_retry_not_before` (1046–1049), reusing the *same* fetched `comments` list to call `ticket_policy.repeat_capped` before dispatching — so a ticket parked by the cap is refused at the one choke point both box (`_dispatch_to_box`) and Mac dispatch share, independent of label state. Covers test 4, and is the regression guard for "fix at the root."
4. **New cross-host test** in `test_run_ticket.py` (or `test_ticket_pipeline.py`, whichever already has the `FakeGitHub`-style comment fixture): two failure comments under different claim labels (`mac-mini-2012` then a Mac label) within 72h park on the second. Covers test 3.
5. **Concurrency + failure-mode tests** (7, 8) using the existing fake-`gh` double pattern from `test_resume_check.py`/`test_parked.py`.
6. **`outside_state.py` or a shared helper**: promote one canonical "failing test ids from pytest output" extractor (reusing `box_runner.FAILED_LINE`'s regex, which is the stricter/more complete of the two existing ones) so `main_health.failed_ids`, `box_runner.failing_tests`, and the new call site below all use it — delete the duplicate.
7. **`evidence_capture.capture_test_results`** (lib/evidence_capture.py:210–223): call `outside_state.parse(output)` on the **full** captured output (before the 600-char `output_tail` truncation) and add the result to the returned dict (`parsed["outside"]`). Covers test 12.
8. **`build_type_measure.py`**: in `_suite_reading`/`measure()`/`PairedMeasure.__call__`, subtract any test id present in `outside`/parsed outside-state failures from that suite's `failed` count before it feeds `metrics_registry.compare()`, mirroring `main_health.verdict()`'s `failed = [t for t in failed_ids(output) if t not in theirs]`. (If Decision flaky-fallback = B, additionally re-run any test name that disagrees between the cached base reading and the current reading before trusting the direction.) Covers tests 10, 11, 13, 14, 15.
9. **`test_portfolio_parity.py`**: fix `_has_playwright()` to also check the Chromium executable (e.g. via Playwright's own `get_executable_path`/driver check, or `shutil.which` on the cached browser path) so the `skipif` correctly skips instead of erroring when only the module is installed. Covers tests 19, 20.
10. **New health-check module** (pattern: `parked.py`/`stale_relay.py`) that reads the 4 known-stale captured-element test ids (from their `outside_state` "what" text or a small allowlist) and reports a dedicated yellow `row()` in `health_checks.run_all()`, so they're visible by name instead of recurring silently in `outside`. Covers tests 21, 22.
11. **`test_dispatch_fallback.py`**: loosen `p.wait(timeout=3)` and the `time.monotonic() - t < 2` wrapper-shutdown-latency assertion to a budget that tolerates `-n 6` contention (tune empirically), without touching the already-generous `test_the_wrapper_still_exits_with_its_jobs_own_code` (`timeout=10`). Verify with 20 consecutive `-n 6` runs per acceptance #3. Covers tests 16–18.
12. **New "sharpen or split" module** (e.g. `lib/sharpen_or_split.py`), reusing `_park_stuck_ticket`'s comment/label mechanics: given a ticket just parked for a review-failure reason (not timeout/vague), runs one agent pass that either rewrites the ticket body with the missing contract (from the recorded `findings`) or splits it into ≤~300-line slices, records which action it took in a comment, and only then restores `ready-for-agent` (removing `needs-info`). Wired per the sharpen-timing Decision above. Covers tests 23–26.
13. Run the full `lib/tests/` suite plus the new/updated ones, and the 20× `-n 6` dispatch-fallback loop, before opening the PR — per [[feedback-full-suites-before-hand-merge]].