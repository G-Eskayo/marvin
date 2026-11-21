1. Add `_route_gh()` and `_od_run()` helpers to `lib/tests/test_work_loop_e2e.py`, reusing the existing `github`/`_gh`/`_reached`/`_gate_log` fixtures without modifying them (the current I2 tests must keep passing unchanged).
2. Write the I1 section: tests 1–4 above, against `bin/gh`'s real `ui_evidence_refusal()`.
3. Write the I3 section: tests 5–9 above, against the real `owner_decisions.py`, routed through the same sandbox env as I1/I2.
4. Write the single end-to-end walk test (10).
5. Write the sandbox-guarantee test (11).
6. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_work_loop_e2e.py -v` locally in this worktree and confirm all pass on today's main, including the existing I2 tests.
7. Confirm each new test fails for the right reason when its guard is disabled (e.g. temporarily stub `pr_images.verdict` to `lambda *a, **k: []`, or `owner_decisions._file` to a no-op, re-run, observe the specific new test fail, then restore) — this is verification of the tests themselves, not a code change to keep.
8. Open the PR noting it reuses `bin/gh`, `lib/pr_images.py`, and `lib/owner_decisions.py` as-is (no production diff), names `marvin#859` and its parent `marvin#737`/ADR 0080, and states plainly that I4–I6 and the dashboard-side fixes (#678, #231, #729) are the next tickets in the ADR's own order, not this one's job.