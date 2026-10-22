## North-star fit

**Reuses:** The substantive design from the prior attempt was sound and I'm keeping it: `HOLD_LABELS` consolidated into `lib/ticket_policy.py` (next to `SKIP_LABELS`) as the one canonical set, `rework_status.status_for`/`collect()` extended with a `_hold_detail` helper mirroring the file's existing lazy-import style, `ticket_agents.plan_refeed`/`plan_stale_claims` switched from the hardcoded `"held" in names` to `names & pol.HOLD_LABELS`, `health_checks.check_hold_revisit`'s shape reused for the new `check_label_contradictions`, and `dashboard/src/lib/holdLabels.js` mirroring `ticket_policy.HOLD_LABELS` for the dashboard side. I verified this is already implemented in this worktree (uncommitted) and is substantially correct — confirmed against `CONTEXT.md:776-802`: `revisit` is deliberately narrower (only `hold`, not `held`/`pinned`) and that distinction is untouched by this change, consistent with the prior plan's test #16.

**What actually caused the regression, found by inspection, not guesswork:** `dashboard/electron/main/decisions_submit.js` imports `isHeld` as `'../lib/holdLabels.js'`. Every other file in `dashboard/electron/main/` that reaches into `dashboard/src/lib/` uses `'../../src/lib/...'` (checked across 13 existing imports — `ticket_input.js`, `merge_ops.js`, `board.js`, `needs_you.js`, etc., all two levels up). `dashboard/electron/lib/` does not exist. This import throws at module load, so any test file that imports `decisions_submit.js` — directly (`decisions_submit.test.js`, 19 tests) or transitively (`mr_actions.test.js` imports it too, 18 tests) — fails to collect entirely. 19 + 18 = 37, matching the reported vitest_passed delta of −36 almost exactly, and explaining why vitest_failed stayed at 0 (a collection crash isn't a test failure, it's tests that silently never ran). The second, smaller gap: task item 12 from the prior plan ("write/extend all tests listed above first... then implement") was only partially done — `test_health_checks.py` was never extended for `check_label_contradictions`, no test covers `run()`'s new contradiction-writing path, and neither `decisions_submit.test.js` nor `pr_state.test.js` got the held-ticket cases the plan itself specified. The prior attempt's process failure, not its design, is what broke: it didn't run the full suite before calling itself done, so a one-character path bug and several missing tests both slipped through.

**Simplest sufficient approach:** fix the one wrong import path (one line) and add the missing tests the prior plan already specified but never wrote — no redesign needed. Rewriting the already-correct Python side or the already-correct wiring in `prState.js`/`ticket_input.js`/`mr_review.js` would spend tokens undoing working code for no reason.

**Tokens:** spends nothing new on design; spends a small, bounded amount on writing the ~6 missing tests and one extra verification pass (running both suites) that the prior attempt skipped — cheaper than another full implementation attempt.

**Capability vs passivity:** unchanged from the prior plan's assessment — this turns a silent contradiction (held + ready + sent-back) into a loud, explained one, which hands control back to Gil rather than removing it.

## Decisions

None needed. The ticket's one open design choice ("refuse vs. silently un-hold") is already answered in the code already present in this worktree: `plan_refeed` refuses and posts a reason for `hold`/`held`, and stays silent only for `pinned` (consistent with the pre-existing "never touch pinned" convention at `CONTEXT.md:779`). No new owner choice has emerged from this investigation.

## Tests first

Everything below either already exists and passes (noted), or is missing and must be added before re-verifying.

**From "How we'll try to break it" / Attacks, already covered (verified present and consistent with pytest's +6/−2 improvement):**
1. `test_held_shows_all_hold_labels` (`lib/tests/test_rework_status.py`) — `held`/`hold`/`pinned` all produce `state == "held"`. Present.
2. `test_held_with_hold_info_shows_details` — detail names who, when, and the comment. Present.
3. `test_a_held_ticket_needing_reengagement_posts_a_comment_instead_of_re_queuing` (`lib/tests/test_ticket_agents.py`) — `held`/`hold` + `needs-reengagement` → no label change, a comment explaining why. Present.
4. `test_a_pinned_ticket_needing_reengagement_is_skipped_entirely` — `pinned` stays silent (no comment, no change), distinct from `held`/`hold`. Present.
5. `leaves a held ticket alone: comment only, no requeue` (`dashboard/test/ticket_input.test.js`) — `held`/`hold`/`pinned` all short-circuit `planInput`. Present.

**Missing — must be added (this is where "verify fails when code changes without a test changing" was actually violated last time):**
6. `lib/tests/test_health_checks.py::test_check_label_contradictions_*` — green on empty/missing contradictions list, red naming the ticket(s) when non-empty, yellow on stale (`age_h > LABEL_CONTRADICTIONS_STALE_HOURS`) or malformed/missing state file, never raises on garbage JSON.
7. `lib/tests/test_ticket_agents.py::test_run_writes_label_contradictions` — a snapshot with a ticket carrying `hold` + `ready-for-agent` (bypassing every guard, as if hand-added) produces a non-empty `write_contradiction_state` write regardless of `cfg["mode"]` (propose or act) — the health check's backstop role must not depend on whether automation is acting.
8. `dashboard/test/decisions_submit.test.js::held ticket answered decisions` — `needs-info` + `hold` ticket, every required decision answered → comment/answers still save, but `out.labelError` explains the hold and the label move to `ready-for-agent` does **not** happen; existing "moves from needs-info to ready-for-agent" case must still pass unchanged for a non-held ticket (regression guard for the exact bug just found).
9. `dashboard/test/pr_state.test.js::held rework state` — `describePrState({ sentBack: true, rework: { state: 'held', ... } })` → headline is "Held: waiting for a person", not "Sent back for rework"; and `rework: { state: 'queued', ... }` / `rework: null` is unchanged (no regression to the common case).
10. Misuse sweep already implicit in #6/#7 but worth stating explicitly: malformed `gh api events`/`gh issue view --comments` output in `rework_status._hold_detail`/`collect()` (empty stdout, non-JSON, nonzero exit, timeout) → `hold_info` is `None`, `collect()` never raises. This is already defended in code (`try/except (TimeoutExpired, JSONDecodeError, ValueError)`) but has no direct test; add one so a future refactor can't silently remove the guard.
11. **Process check, not a unit test:** after 1–3 below, run the full `pytest` and `vitest` suites and diff total passed/failed against the baseline in the metrics comparison (5242/2 and 2070/0). Any unexplained drop in passed count — even with 0 new failures — blocks completion. This step was skipped last time; it is now mandatory before reporting done.

## Task List

1. Fix `dashboard/electron/main/decisions_submit.js`: change `import { isHeld } from '../lib/holdLabels.js'` to `'../../src/lib/holdLabels.js'`, matching the convention used by every other file in `dashboard/electron/main/` (`ticket_input.js`, `merge_ops.js`, `board.js`, etc.).
2. Add test 6 (`check_label_contradictions`) to `lib/tests/test_health_checks.py`.
3. Add test 7 (`run()` contradiction write, propose and act modes) to `lib/tests/test_ticket_agents.py`.
4. Add test 8 (held + needs-info + answered decisions) to `dashboard/test/decisions_submit.test.js`.
5. Add test 9 (held rework state) to `dashboard/test/pr_state.test.js`.
6. Add test 10 (`_hold_detail`/`collect()` malformed-`gh`-output guard) to `lib/tests/test_rework_status.py`.
7. Confirm tests 2–6 fail against the current code only where expected (6 should already pass once #1 is fixed; 2–5 are genuinely new coverage) — i.e. verify each new test is actually exercising new behavior, not a no-op.
8. Run the full `pytest` and `vitest` suites; compare total passed/failed against baseline (5242 tests_passed / 2 tests_failed, 2070 vitest_passed / 0 vitest_failed, 3172 pytest_passed / 2 pytest_failed). Do not report completion until there is no unexplained drop anywhere.
9. Optional, low-cost: add a one-line note to `CONTEXT.md`'s ticket-agents section (near `776-802`) recording the `HOLD_LABELS` consolidation and the `check_label_contradictions` health check, consistent with how `#387`/`#357` style fixes are already documented inline rather than as a separate ADR.