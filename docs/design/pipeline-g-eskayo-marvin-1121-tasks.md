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