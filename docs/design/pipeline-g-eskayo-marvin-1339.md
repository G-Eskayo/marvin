## North-star fit

**Reuses, before adding anything new:**
- The per-ticket park trigger already exists and is already host-agnostic by design: `run_ticket._trailing_streaks`/`_consecutive_failure_streak` (`lib/run_ticket.py:96-139`) counts `FAILURE_MARKER`/`TIMEOUT_MARKER` comments on the shared GitHub issue thread — not a per-machine log — specifically so "both machines agree on it for free." `failure_breaker.py`'s log (`~/.claude/logs/pipeline-failures.jsonl`) is **not** in `~/.claude`'s synced path allow-list (confirmed against `project-marvin-cross-machine-sync.md`: only `CLAUDE.md`, `lexicon.md`, `memory/`, `commands/`, `handoffs/` and a few backlogs sync — `logs/` is excluded), so it is genuinely per-machine. I will **not** rebuild the park-cap on that log (the tempting reuse target) — that would reintroduce exactly the cross-host gap the ticket is about. I'll extend the existing GitHub-comment mechanism instead, adding the missing time bound and lowering the cap, and add the regression test the ticket explicitly asks for (box failure + Mac failure counted together) to lock this in.
- `outside_state` (`lib/outside_state.py`, marvin#1047) already exists for exactly "a test that checks state outside this repo's code." The portfolio parity/elements tests are already marked with it, and `main_health.py` already reports them as yellow, not red. The gap is that `build_type_measure.py`'s ticket-level pytest invocations (`_measure_commands`, `PairedMeasure._pytest`/`_pytest_at_base`) don't deselect them, so they still enter every ticket's own baseline/after comparison. Fix is a one-flag reuse (`-m "not outside_state"`), not a new mechanism.
- `denial_diagnosis.classify()` (`lib/denial_diagnosis.py`) is the existing pattern for "one bounded `marvin_launcher.launch("background-analyst", ...)` call that reads a ticket + failure context, returns a short structured verdict, and the deterministic Python wrapper posts/acts on it." The new "sharpen or split" pass reuses this shape rather than inventing a new agent-invocation pattern.
- `ticket_policy.is_parent_prd` + `_unclaimed_ready_tickets`'s existing "skip parent PRDs" filter (`lib/ticket_pipeline.py:143-147`) is reused if splitting creates sibling tickets under a parent, instead of inventing new dispatch-skip logic.

**Simplest sufficient approach:** no new storage, no new cross-machine sync path, no new daemon. Three surgical, independently testable changes to existing modules (`run_ticket.py`, `build_type_measure.py`/`evidence_capture.py`, `test_dispatch_fallback.py`) plus one small new best-effort side-call (`_park_stuck_ticket`→sharpen-or-split), wired the same best-effort way every other side-step in this pipeline already is (`_owner_decisions`, `_parked`, `_post_fit_check`): never blocks or crashes the run it's attached to.

**Where it spends tokens:** the new "sharpen or split" pass is one bounded `background-analyst` call per park-on-review-failure event (same cost shape as `denial_diagnosis`, which already runs today) — not per build round. Everything else (the 72h window, the marker deselect, the test-timing fix) is free at build time (pure Python / a pytest flag already in use elsewhere).

**Phone-OS direction:** indirect — this is pipeline throughput, not a phone-reachable feature, but a backlog that actually flows is what lets MARVIN keep building the OS-direction work at all.

**User more capable, not more passive:** yes — it stops Gil from having to notice "0 PRs for 2 days" by hand (which is how this ticket itself got filed) and replaces silent repeat-building with a named reason + a self-correcting rewrite/split step, so the next thing he sees is a sharper ticket or a question, not another dead rebuild.

**Machine:** plan only, no build; the eventual PR(s) run wherever the pipeline already dispatches marvin tickets (Mini/laptop/box) — nothing here is machine-specific.

---

## What's actually broken, read from the code (not reasserted from the ticket)

1. **Repeat cap (acceptance 1):** `MAX_CONSECUTIVE_FAILURES = 3` (`run_ticket.py:39`) is unbounded in time — `_trailing_streaks` walks backward with no cutoff, stopping only at a pass/handoff/person comment. The acceptance wants `N=2` **within a 72h window**. This is a real behavior gap (today a ticket could fail twice a week apart and never park), not just a hunch — and it's the natural place a single real "pass" (a PR raised that later gets sent back by GitHub CI/`_requeue_conflicted_prs`, unrelated to the internal must-fix gate) could reset counting to zero and let a ticket cycle indefinitely without ever hitting 3 *consecutive* internal failures, matching "130 rounds, 1 PR" better than a true counting bug would. The fix (count failures by elapsed time, not strict unbroken consecutiveness) closes both the literal acceptance text and this dilution path at once.
2. **Red baseline / mixed (acceptance 2):** `metrics_registry.compare()` (`lib/metrics_registry.py:141-188`) has `ABSOLUTE_TOLERANCE = 1e-9` — a single test flipping on either side registers as a direction change. `build_type_measure.PairedMeasure` already re-runs the *same* test selection on base and after every time, but only returns aggregate `passed`/`failed` counts (`evidence_capture.parse_test_output`, `lib/evidence_capture.py:37-75`) — no per-test identity — so a test that's flaky or already red on both sides can't be told apart from a real regression.
3. **The flaky test (acceptance 3):** `test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` (`lib/tests/test_dispatch_fallback.py:444-459`) asserts `p.wait(timeout=3)` and `time.monotonic() - t < 2` — tight enough to catch the real bug it guards (a 30s wrapper-waits-for-its-job regression, per its own docstring) but tight enough to also flag under `-n 6` scheduler contention.
4. **Host-only checks (acceptance 4):** already solved for *reporting* (`outside_state.py` + `main_health.py`); not yet solved for *ticket-level pollution*, per point 2 above — `_measure_commands`/`PairedMeasure` don't deselect `outside_state`-marked tests.
5. **Sharpen-or-split (owner's comment addition):** no existing mechanism splits/rewrites a ticket on repeated review-must-fix parks. Nearest reusable shape is `denial_diagnosis.classify()`.

---

## Tests to write first

**Acceptance 1 — repeat cap, cross-host, 72h window**
1. Two failures from different `claim_label`s (simulating a box settle then a Mac settle) on the same ticket within 72h park it at N=2 — the literal "box run followed by a Mac run" case the ticket asks for.
2. A failure older than 72h does **not** count toward the current window (a ticket that failed once last week and once today is not parked on the second alone).
3. Two failures both inside 72h still park even with a `PASSED_MARKER`/"sent back" comment interleaved between them (the dilution case found above) — locks in that a real pass doesn't quietly reset the window within 72h.
4. A `MODEL_MARKER` (usage-limit) comment between two real failures is still skipped (not counted, not a reset) — existing behavior must not regress.
5. A person's own comment between two failures still resets the window (existing "handoff ends a streak" behavior preserved).
6. Exactly N-1 failures in 72h does not park; the Nth does, with the correct `reason` and `findings` carried into the park comment.
7. `gh issue comments` returning `None` (API unreadable) fails safe — never parks on missing data, never crashes the run (misuse: dependency failure).
8. A ticket with a large comment history (50+ comments, repeats/noise) still counts correctly — guards against any pagination truncation in `_issue_comments`.

**Acceptance 2 — ignore red-on-base / re-run single-sided failures**
9. A test marked `outside_state` failing on both base and after never appears in the ticket's `tests_failed` delta (deselected outright).
10. A test that fails on `after` only, and fails again on a targeted re-run, counts as a real regression (verdict stays `mixed`/`regressed`).
11. A test that fails on `after` only, but **passes** on a targeted re-run, is excluded from the comparison (not counted as a new failure) — the actual flake case.
12. A test failing on `base` only (fixed by the change) is not inflated into a bigger "improved" signal than the real change made — base-only failures are neutral, not scored.
13. The re-run step itself times out or crashes (dependency failure: a hung subprocess) — must not crash `PairedMeasure`, falls back to counting the original reading.
14. Base and after have a *different* set of outside_state tests selected (e.g. a ticket touches portfolio code) — still deselected on both sides consistently.

**Acceptance 3 — the flaky test, fixed outright**
15. `test_a_signal_to_the_wrapper_alone_ends_it_and_its_job_at_once` passes 20/20 runs under `-n 6` (the acceptance's literal bar) — a bench-style repeat-run check, not just one green run.
16. The widened timing margin still catches the real regression it exists for: a wrapper that *does* wait for its job (reintroducing the pre-#1139 bug synthetically) still fails the test, so the fix doesn't gut its purpose.

**Acceptance 4 — host-only checks out of every ticket's baseline**
17. `_measure_commands()`'s pytest command includes `-m "not outside_state"`.
18. `PairedMeasure`'s base and after pytest commands both include the deselect, and a ticket that doesn't touch portfolio code never even collects those tests (no behavior change to runtime for the common case).
19. `main_health.py`'s own run is unaffected — outside_state tests still execute and still report under `main:green`'s yellow/`outside` path (regression guard: this ticket must not quietes the reporting it's not supposed to touch).

**Sharpen-or-split (owner's added criterion)**
20. A park with non-empty `findings` (review-failure park) triggers exactly one `marvin_launcher.launch` call; a park with no `findings` (timeout/vague park) triggers none.
21. The analyst's "rewrite" verdict results in exactly one `gh issue edit --body`, removes `needs-info`, adds `ready-for-agent`, and posts a "rewrote the contract" record comment.
22. The analyst's "split" verdict (decision-dependent on the Decision below) results in the chosen split mechanic, and the ORIGINAL ticket is never put back to `ready-for-agent` directly.
23. The analyst gives no answer / a malformed answer (dependency failure: model returns garbage) — ticket stays parked in `needs-info`, nothing is guessed, and this is itself logged as a problem rather than silently no-op'd.
24. A failing `gh` call anywhere in the sharpen-or-split path never crashes the run it's attached to (matches every other best-effort side-call in this file).
25. Running sharpen-or-split twice on the same park event (retry/misuse: a redispatch race re-triggers settle) doesn't double-post or double-split — idempotent on an already-sharpened/already-split ticket.

---

## Decisions
<!-- marvin:decisions -->
### split_mechanic: When the sharpen-or-split pass decides to split a parked ticket into ≤300-line slices, how should the split be represented?
- [ ] A: New sibling GitHub issues (one per slice), each `ready-for-agent`; the original ticket is labelled/treated as a parent PRD (reuses `ticket_policy.is_parent_prd`'s existing dispatch-skip) and stays open only as a tracker
- [ ] B: Rewrite the same ticket's body into an in-ticket checklist of slices; the ticket goes back to `ready-for-agent` as one ticket, and the builder works through the checklist across however many PRs it takes

### park_cap_default: The acceptance text says N=2 failures in 72h; confirm this applies globally (box + both Macs + any other registered project), not just marvin
- [ ] A: Yes, `MAX_CONSECUTIVE_FAILURES`/window change applies to every project that runs through `run_ticket.py`, not just `G-Eskayo/marvin`
- [ ] B: marvin only for now; other projects keep the old unbounded-consecutive cap until proven out here

---

## Task List

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