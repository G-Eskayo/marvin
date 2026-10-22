1. Fix `dashboard/electron/main/decisions_submit.js`: change `import { isHeld } from '../lib/holdLabels.js'` to `'../../src/lib/holdLabels.js'`, matching the convention used by every other file in `dashboard/electron/main/` (`ticket_input.js`, `merge_ops.js`, `board.js`, etc.).
2. Add test 6 (`check_label_contradictions`) to `lib/tests/test_health_checks.py`.
3. Add test 7 (`run()` contradiction write, propose and act modes) to `lib/tests/test_ticket_agents.py`.
4. Add test 8 (held + needs-info + answered decisions) to `dashboard/test/decisions_submit.test.js`.
5. Add test 9 (held rework state) to `dashboard/test/pr_state.test.js`.
6. Add test 10 (`_hold_detail`/`collect()` malformed-`gh`-output guard) to `lib/tests/test_rework_status.py`.
7. Confirm tests 2–6 fail against the current code only where expected (6 should already pass once #1 is fixed; 2–5 are genuinely new coverage) — i.e. verify each new test is actually exercising new behavior, not a no-op.
8. Run the full `pytest` and `vitest` suites; compare total passed/failed against baseline (5242 tests_passed / 2 tests_failed, 2070 vitest_passed / 0 vitest_failed, 3172 pytest_passed / 2 pytest_failed). Do not report completion until there is no unexplained drop anywhere.
9. Optional, low-cost: add a one-line note to `CONTEXT.md`'s ticket-agents section (near `776-802`) recording the `HOLD_LABELS` consolidation and the `check_label_contradictions` health check, consistent with how `#387`/`#357` style fixes are already documented inline rather than as a separate ADR.