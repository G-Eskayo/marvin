No conflicting policy. Now writing the plan.

## North-star fit

Reuses the existing PROBE_CMD-faking pattern already in this file (`lib/tests/test_disk_ledger.py:267,275`, `test_a_folder_this_job_may_not_read_is_reported_protected_and_never_walked` / `test_a_probe_that_blocks_on_a_privacy_prompt_counts_as_protected`) and the `_script()` helper (`lib/tests/test_disk_ledger.py:187`) that both already use to stand in for `du`/`ls`. No new helper, no production-code change: the flakiness lives entirely in `_du_nice_under` (`lib/tests/test_disk_ledger.py:286`), which fakes `DU_CMD` but leaves `PROBE_CMD` pointed at the real `/bin/ls -f`. That probe's child is reniced to `parent_nice + 10` (capped at 19) by `disk_ledger._bounded`'s `limit()` (`lib/disk_ledger.py:57`), so at `parent_nice=15` the probe runs at nice 19 — easy to starve past `PROBE_TIMEOUT_S=10` under a loaded parallel run, which makes `du_kb` return `NOT_MEASURED_PROTECTED` (`lib/disk_ledger.py:83`) and the forked test child exit 1 with no diagnostic. This is the simplest sufficient fix: one `monkeypatch.setattr(dl, "PROBE_CMD", ...)` line removes the only system-load-sensitive step from a test that is only supposed to exercise nice values, plus surfacing `_default_du_kb`'s actual return value on failure. It costs nothing extra at runtime (the fake probe exits immediately, same cost class as the already-faked `du`) and it saves tokens/time at the merge gate by removing retries and send-backs caused by this noise (north star 1). No phone-OS or machine-choice dimension — pure test-isolation fix, runs wherever the suite runs (mac-mini per the ticket's `claimed:mac-mini` label). It leaves the signal more trustworthy rather than making anyone more passive — a red run can be trusted and a green run isn't luck.

The ticket's own "Purpose" line says root cause, not retry — checked against the code and it holds; nothing to correct.

## Tests to write first

From "How we'll try to break it":

1. **`test_du_nice_under_reports_cause_on_failure`** (new) — force `_default_du_kb` to return a non-1 value inside the forked child (e.g. monkeypatch `PROBE_CMD` to the existing "not permitted" fake pattern from `test_a_folder_this_job_may_not_read_is_reported_protected_and_never_walked`) and assert `_du_nice_under` raises with a message that names the actual returned reason (e.g. contains `"not measured"`). Directly targets acceptance criterion 1 ("failure names its cause") and is the only genuinely new behavior being added.
2. **`test_du_runs_at_low_priority[0,5,9,10,15,19]`** (existing, modified) — after faking `PROBE_CMD` to return instantly, the existing assertions must still pass at every parametrized value, including 19. This is the regression test for the reported flake itself.
3. **Repeated/parallel execution check** (not a new pytest function — a verification run, since the bug is timing-dependent): `-n auto`, 20 iterations in a row, plus the full suite running alongside at least once. This is acceptance criterion 3; results get recorded in the PR body as the reproduction evidence the ticket asks for.
4. **Planted-bug check** (manual verification during implementation, not a committed test): temporarily remove `os.nice(10)` from `disk_ledger._bounded`'s `limit()` and re-run `test_du_runs_at_low_priority`, confirming it still goes red. Satisfies acceptance criterion 4 — proves the fix didn't defang the test's actual nice-value assertion while making it immune to the probe's real-subprocess timing.
5. **Root-cause confirmation step** (diagnostic, done before the fix, per the ticket's own instructions): temporarily make the forked child write `_default_du_kb`'s return value to the out file unconditionally (not just on nice-read success), then reproduce under `-n auto` with concurrent CPU load (several busy loops at nice 0) to confirm the failure reason is indeed `NOT_MEASURED_PROTECTED`/probe timeout, before committing to the PROBE_CMD-fake fix. This instrumentation becomes test 1 once confirmed, rather than staying as a one-off.

Other tests in the file that call `_default_du_kb`/`du_kb` on a real path without faking `PROBE_CMD` (`test_du_keeps_the_total_when_some_folders_are_unreadable`, `test_garbage_du_output_is_not_measured_not_a_crash`, `test_a_du_that_cannot_start_is_not_measured`, `test_a_du_that_never_returns_is_killed_and_reported_not_measured`, `test_the_du_dies_on_its_own_even_when_its_parent_is_killed`) share the same unmocked-real-probe exposure, but none of them renice up to 19 the way the parametrized test does, so they're lower-risk and out of this ticket's stated scope — flagged below as a Decision rather than silently fixed or silently left.

## Decisions

<!-- marvin:decisions -->
### other-tests: Also fake `PROBE_CMD` in the other unmocked-probe tests now, or leave for a separate ticket?
- [ ] A: Fix only `_du_nice_under`/`test_du_runs_at_low_priority` (this ticket's exact scope); file a follow-up ticket for the other five tests that share the same unmocked-real-probe pattern
- [ ] B: Fix all six in this PR while touching the file, since it's the same one-line pattern repeated

## Task List

1. Instrument `_du_nice_under` to write `_default_du_kb`'s actual return value to a result file regardless of outcome (diagnostic step, confirms root cause before the fix).
2. Reproduce under `pytest -n auto` with concurrent CPU load (busy loops at nice 0) and confirm the named cause is a probe timeout / `NOT_MEASURED_PROTECTED`.
3. Fix: `monkeypatch.setattr(dl, "PROBE_CMD", [_script(tmp_path, "probe", "exit 0")])` in `_du_nice_under`, reusing the existing `_script()` fake-executable pattern (`lib/tests/test_disk_ledger.py:187`).
4. Update `_du_nice_under`'s failure path so a non-zero child exit raises/asserts with the recorded return value in the message (acceptance criterion 1).
5. Add `test_du_nice_under_reports_cause_on_failure` (new regression test for the "names its cause" behavior).
6. Run `test_du_runs_at_low_priority` for all six parametrized `parent_nice` values and confirm green.
7. Run `lib/tests/test_disk_ledger.py` under `-n auto` 20 times in a row; run the full test suite alongside at least once; capture pass evidence for the PR body.
8. Planted-bug check: temporarily drop `os.nice(10)` from `disk_ledger._bounded`'s `limit()`, confirm `test_du_runs_at_low_priority` goes red, then revert.
9. Resolve the `other-tests` Decision (owner answers via PR buttons) and act on it — either file the follow-up ticket (A) or apply the same `PROBE_CMD` fake to the other five tests in this PR (B).
10. Write the PR body with root cause, the reproduction that showed it, and the 20-run + full-suite evidence; `marvin-show` the relevant diff/log if useful for review.