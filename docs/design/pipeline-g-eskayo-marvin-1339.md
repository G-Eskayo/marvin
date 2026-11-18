## North-star fit

**Reuses before adding anything new:**
- The per-ticket backoff gate `_retry_not_before()` (`lib/ticket_pipeline.py:710-726`) already exists and is already called on the normal dispatch path (`_dispatch_one`, `ticket_pipeline.py:1046`) — AC1's fix is to call it from `_box_fallback()` (`ticket_pipeline.py:1121-1139`) too, not invent new state.
- The per-ticket strike/park machinery (`run_ticket._consecutive_failure_streak`/`_trailing_streaks`, `ticket_policy.automated_comment`/`retry_marker`) already reads a GitHub issue's own comment thread, which is naturally shared across every host — no new cross-host store needed, just retuning its shape (N, window) to match the acceptance text.
- `outside_state.py` (`lib/outside_state.py`) is the exact existing pattern for "this failure is the environment's, not the code's, and main-health shows it yellow by name instead of failing main" — AC4 reuses it rather than inventing a second mechanism.
- `main_health.failed_ids()` (`lib/main_health.py:44-45`, `re.finditer(r"^FAILED\s+(\S+)", ...)`) is the existing per-test-ID extraction pattern to reuse inside `build_type_measure.py` for AC2, instead of writing a new parser.

**Why this is the simplest sufficient approach:** each acceptance criterion maps to one concrete, already-demonstrated code defect or gap rather than a redesign:
1. `_box_fallback()` dispatches a later linux-ok ticket without ever calling `_retry_not_before()` — confirmed by reading `ticket_pipeline.py:1121-1139` side-by-side with `_dispatch_one` (`:1046-1049`), and by `test_ticket_pipeline.py`'s own conftest stubbing `_retry_not_before` to always return `None`, which is why no existing test caught the gap.
2. `metrics_registry.compare()` (`lib/metrics_registry.py:150-188`) only ever sees aggregate pass/fail counts (`build_type_measure.py`'s `_metrics()`/`_suite_reading()`), never per-test identity, so it structurally cannot tell "a test that was already red on base flipped" from "the ticket regressed something."
3. `test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` (`lib/tests/test_dispatch_fallback.py:444-459`) asserts hard-coded 2s/3s wall-clock budgets around real subprocess + real-signal delivery; the implementation it tests (`task_dispatch.py:434-446`, the `#1139` fix) is already correct — this is a test-timing flake, not a production bug.
4. The portfolio-parity/elements tests (`lib/tests/test_portfolio_parity.py:53-63`, 7 `ELEMENT_IDS`) are already marked `outside_state`, but their `skipif` (`:58`) only checks the `playwright` *package*, not the chromium *browser binary* — so a missing browser cache runs (and fails) the test instead of skipping it.

**Where it spends/saves tokens:** every fix is a targeted code change plus tests, no new agents/LLM calls added to the hot path. AC1's fix directly reduces wasted build-agent runs (the thing the ticket is about — ~130 rounds, 1 PR).

**Phone-OS direction:** neutral — this is pipeline reliability, not user-facing.

**More capable or more passive:** more capable — it stops wasted machine-hours on tickets that can't pass, redirecting that capacity (north star 5) to tickets that can, and surfaces (rather than hides) host-only gaps in the health report so a person can act on them.

## Tests to write first

Per ticket's "How we'll try to break it" / Attacks: none are listed explicitly, so these are derived from the acceptance criteria plus the owner's comment feedback, following the adversarial-TDD rule (bad/empty/huge/malformed input, each dependency failing, repeats/concurrency/order, wrong permissions, stale state, a person's mistakes):

**AC1 — repeat cap holds across hosts, box fallback honors backoff**
1. `test_ticket_pipeline.py`: `_box_fallback` skips a later linux-ok ticket whose `_retry_not_before` says it must wait (mirrors `test_when_no_mac_can_take_the_first_ticket_the_box_builds_a_later_linux_ok_one` but stubs `_retry_not_before` to return a future time for ticket #6; assert `starts == []` and the next eligible ticket, if any, is tried instead).
2. `test_ticket_pipeline.py`: a later ticket whose backoff has already expired is still built on the box (regression guard against over-fixing to "never dispatch").
3. `test_run_ticket.py`: a box settle (`claim_label="mac-mini-2012"`) followed by a Mac settle (`claim_label=None`) on the *same* issue, with real (unmocked) `_issue_comments` fixture data, parks at the new default `N=2` — the literal "box run followed by a Mac run" case the ticket asks for.
4. `test_run_ticket.py`/`test_ticket_policy.py`: the 72h window — two failures more than 72h apart do **not** park (the ticket "ages out", matching "in the last 72 h"); two failures within 72h do.
5. `test_ticket_policy.py`: malformed/missing `createdAt` on a comment degrades safely (treated as "doesn't count toward the window" rather than crashing or wrongly parking/never-parking).
6. Existing `test_consecutive_failure_streak_*` and `test_run_parks_the_ticket_instead_of_releasing_at_the_failure_cap` must still pass with the new default (update their literal expectations from `MAX_CONSECUTIVE_FAILURES`'s old value).

**AC2 — red-on-base tests can't make a result "mixed"**
7. `metrics_registry.py` or `build_type_measure.py` (wherever the chosen fix lands, per the Decision below): a test failing identically on base and after is excluded from the delta — verdict is computed from the *other* metrics only.
8. A test that fails on base but passes after is a real improvement (not suppressed).
9. A test that passes on base but fails after is a real regression (still caught — the fix must not blanket-hide genuine regressions).
10. Every test in the selection red on both sides and nothing else changed → `"unchanged"`, not `"mixed"` or `"regressed"`.
11. Base run itself crashes/produces no summary → `MeasureError`, never silently treated as "0 failures, ignore everything" (existing `MeasureError` contract in `build_type_measure.py:131-138` must still hold).
12. If the "re-run mismatched before counting" branch of the Decision is chosen: a test that disagrees between base and after is re-run once; if the rerun agrees with the other side, the original disagreement is dropped; if it doesn't, it counts as a real signal — test both outcomes.

**AC3 — the flaky signal test passes 20x under `-n 6`**
13. Run `test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` (all 3 signal params) 20 times in a row under `pytest -n 6` as the acceptance check itself (not a new unit test, but the verification gate for this change).
14. Keep a regression test that the *old* bug (wrapper waiting out its job, ~30s) is still caught by the widened budget — i.e., the new margin must be well under 30s so a real regression still fails fast, not just "eventually".

**AC4 — host-only checks say why, instead of polluting every ticket's baseline**
15. `test_portfolio_parity.py`: `_has_playwright()` (or its replacement) returns `False` when the package is importable but the chromium browser binary is absent (mock the browser-cache path missing) — the test is skipped, not failed, on such a host.
16. `health_checks.py`: a new/extended check reports yellow with "needs Playwright chromium / the live dev site" by name when this machine lacks them, and returns the existing `None`/"not applicable" shape on a machine that fully has them (matching `check_graphify_fresh`'s convention).
17. `build_type_measure.py`/`PairedMeasure`: a ticket's test selection that includes a portfolio-parity test on a host lacking the dev site does not fail that ticket's comparison merely for lacking the host dependency (ties into AC2's red-on-base exclusion, since skip ≠ fail already helps, but a *stale capture* failure — package+browser present, dev site reachable, but restyled — still needs AC2's handling, not a skip).
18. A host that *does* have Playwright+dev site still runs and enforces the parity tests normally (no accidental global skip).

**Misuse/edge cases the ticket's list didn't name, per the north-star checklist:**
19. `gh issue view --json comments` failing/timing out mid-streak-count (network blip) — must fail open (don't park on a read failure) per the existing `_issue_comments` contract (`run_ticket.py:70-82`) — add a test if the 72h-window change touches that function's error handling.
20. Two scans on two different machines racing to re-dispatch the same backoff-expired ticket to the box at once — covered by the existing `_claim_is_ours_alone` race guard; add a test only if the `_box_fallback` fix changes claim ordering (it shouldn't — `_dispatch_to_box` is unchanged).
21. A person manually commenting on a ticket mid-streak must still reset the window-based count the same way it resets the old consecutive count (reuse `ticket_policy.automated_comment`'s "a person's comment ends it" rule — verify it still holds with the time-window change).

## Decisions
<!-- marvin:decisions -->
### red_baseline_fix: How should the ticket comparison stop a red/flaky base test from producing "mixed"?
- [ ] A: Exclude any test that fails identically on both base and after from the delta (simpler, only helps *persistently* red tests, e.g. the host-only portfolio-parity ones)
- [ ] B: Re-run once any test whose pass/fail status disagrees between base and after before counting it (handles genuine flakiness too, e.g. the dispatch-fallback test before its own fix lands; costs one extra test invocation per disagreement)
- [x] C: Both — exclude same-sides-red tests outright, and re-run only the ones that disagree

### cap_default: Confirm the new per-ticket repeat-cap default
- [x] A: N=2 full runs in 72h, exactly as the acceptance text states (lowers the current default of 3 with no time window)
- [ ] B: Keep N=3 but add the 72h window (less aggressive parking, still closes the box/Mac asymmetry)

## Task List

1. **Fix `_box_fallback`'s missing backoff check** (`lib/ticket_pipeline.py:1121-1139`): call `_retry_not_before(repo, ticket)` for each candidate in `rest` and skip (continue, don't return `None` outright — a later ticket may still be eligible) any ticket still backing off, mirroring `_dispatch_one`'s check at `:1046-1049`.
2. Add tests 1-2 (box-fallback honors/doesn't-wrongly-apply backoff) to `lib/tests/test_ticket_pipeline.py`.
3. **Retune the per-ticket park cap** in `lib/run_ticket.py`/`lib/ticket_policy.py`: change `MAX_CONSECUTIVE_FAILURES` to the Decision's chosen default, and add a 72h time window to `_trailing_streaks`/`_consecutive_failure_streak` by reading each comment's `createdAt` (extend `_issue_comments`'s `--json` fields to include it) and only counting comments within the window.
4. Add tests 3-6 to `lib/tests/test_run_ticket.py` (and `test_ticket_policy.py` if the window logic moves there), including the explicit box-settle-then-Mac-settle case.
5. **Fix the flaky signal test**: widen the wall-clock budgets in `test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` (`lib/tests/test_dispatch_fallback.py:444-459`) and its sibling tight-timing tests (`:478-496`, `:498-515`) to tolerate `-n 6` scheduling contention, keeping the margin well under the ~30s the old bug produced (test 14).
6. Run it 20x under `-n 6` to confirm (acceptance check, test 13).
7. **Extract per-test failure IDs** in the paired measure: add a `failed_ids()`-style helper (reusing `main_health.py:44-45`'s pattern) to `evidence_capture.py` or `build_type_measure.py`, surfaced alongside the existing aggregate counts from `PairedMeasure._pytest`/`_pytest_at_base` (`build_type_measure.py:343-381`).
8. **Implement the chosen red-baseline fix** (per the `red_baseline_fix` Decision) in `build_type_measure.py`/`metrics_registry.compare()`, and add tests 7-12.
9. **Fix the Playwright-cache detection**: replace/extend `_has_playwright()` in `test_portfolio_parity.py:33-35` to also check the chromium browser binary is actually installed (not just the `playwright` package), so a missing cache skips rather than fails. Add test 15.
10. **Add the host-only health check**: a new check in `lib/health_checks.py` (following `check_graphify_fresh`/`check_site_published`'s shape) registered in `default_checks()` (`:1796-1835`) that reports yellow-by-name when this host lacks Playwright chromium or the live dev site, `None` ("not applicable") when it has them and everything's fine. Add test 16.
11. Add tests 17-18 confirming a host lacking the dependency doesn't fail a ticket's build-time comparison, and a host that has it still enforces parity normally.
12. Add tests 19-21 for the identified edge cases (comment-read failure, race, person-comment reset) if the changes above touch that code path.
13. Run the full Python suite plus the targeted `-n 6` x20 check before raising the PR (per CLAUDE.md's full-suites-before-merge rule), and update `CONTEXT.md`/an ADR entry noting the new repeat-cap shape and the red-baseline-exclusion decision made.