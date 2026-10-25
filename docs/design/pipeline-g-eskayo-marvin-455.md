Write access is restricted in this environment (planning-only step — the orchestrator persists the doc itself), so here's the plan as my response.

## ⚠️ Live blocking signal — unchanged from the prior attempt, re-verified just now

`gh issue view 455 --repo G-Eskayo/marvin` right now shows labels **`bug`, `ready-for-agent`, `claimed:mac-mini`, `hold`, `project:marvin`, `priority:p2`** — `hold` and `ready-for-agent` both still present, the exact held-and-ready contradiction this ticket exists to detect, on itself. The most recent comment (Gil, 2026-10-22T20:20:06Z — later than every retry/verification-failure bot comment in the thread) reads:

> "On hold (Gil, 2026-10-22): the pipeline kept planning this ticket over and over. 'Needs a person' did not stop the dispatcher or the conflict checker, and bot comments reset the failure count. The fix is being built on its own ticket. Remove `hold` to put this back in the queue."

Nothing since then removes `hold`. The prior attempt flagged this and planned anyway, and the record shows the pipeline went ahead and implemented — code review's last note was explicit: *"This PR's existence suggests the pipeline went ahead anyway, which is the loop this ticket is meant to stop."* I'm producing this plan for the same reason the prior attempt did (planning is low-cost, leaves a correct plan behind), but **dispatch must not pick this up for implementation while `hold` is still on the issue.** That's Gil's call, not something to work around a second time.

## North-star fit

**Reuses, re-confirmed by reading the actual worktree** (the uncommitted diff already sitting there is a prior implementation attempt kept as the starting point, not re-derived):
- `ticket_policy.HOLD_LABELS` (`lib/ticket_policy.py:16`) is canonical; `ticket_pipeline.py:113` now aliases it instead of duplicating the frozenset — already fixed, keep.
- `ticket_agents.plan_refeed` (`lib/ticket_agents.py:178`) already skips `needs-reengagement` tickets carrying a `HOLD_LABELS` member — correct, matches AC3.
- `ticket_agents.write_label_conflicts` (`lib/ticket_agents.py:317`) already mirrors `write_revisit_state`'s tmp-then-rename + truncate-at-50 pattern. Correct.
- `health_checks.check_label_conflicts` (`lib/health_checks.py:504`) already mirrors `check_hold_revisit`'s stale/missing/green/red shape. Correct shape, one message bug (fixed below).
- `dashboard/src/lib/hold_labels.js` (new) is the single JS source of truth, already consumed by `ticket_input.js:8`. **Not yet consumed by `decisions_submit.js`**, which keeps its own local `new Set(['pinned','hold','held'])` — exactly the duplication `hold_labels.js` exists to prevent. `decisions_submit.js` sits in `dashboard/electron/main/`, which already imports from `src/lib/*.js` in ten other files (`board.js`, `boards.js`, `deliverables.js`, `docs.js`, `merge_ops.js`, `outbox.js`, etc.) — so `import { isHeld } from '../../src/lib/hold_labels.js'` is the existing pattern, not a new one.
- `project_catalog.run_env()` (used via `ticket_agents._gh`, `lib/ticket_agents.py:506`, and `auto_merge_shadow.py:193`) is the existing pattern for giving a `gh` subprocess call a PATH that actually has `~/.agents/bin/gh` (the rate-limit gate) first. `rework_status._hold_info` (`lib/rework_status.py:68`) is the one `gh` call site in the touched files not going through it.
- `_result` and the file's dominant `except Exception` convention (9 other call sites in `health_checks.py`) is the "never crash a health check" pattern. `check_label_conflicts` and `check_hold_revisit` narrow this to `(OSError, ValueError, KeyError)` — out of step, and the cause of one must-fix defect.

**What's still broken (verified against the current diff, not re-guessed):**

1. `lib/tests/test_ticket_agents.py:551` (`test_write_label_conflicts_truncates_at_50`) still writes to a hardcoded `Path("/tmp/test_label_conflicts")` instead of the `tmp_path` fixture the test two lines above it already uses correctly. Confirmed unfixed.
2. `lib/rework_status.py:73,87` (`_hold_info`) still call `gh api .../events` and `.../comments` with no `--paginate`. Confirmed unfixed. Two compounding bugs:
   - **No pagination** — a ticket with >30 events/comments (exactly #455's own shape) can have its real latest hold event or matching comment past page 1, so `_hold_info` reports a stale hold's date/reason, or nothing.
   - **Only `labeled` events considered, blind to `unlabeled`** — if a hold label was removed then a *different* hold label added later, the function has no way to tell "still held since X" from "held again since Y," because it never tracks when a label stopped being active.

**Two smaller, same-shape bugs in the same functions, free to fix alongside them:**
- `rework_status.py:124`: `next((l for l in names if l in HOLD_LABELS), "held")` iterates a `set` — nondeterministic which label gets named when a ticket carries two. `sorted(...)` fixes it.
- `health_checks.py:504-523`: the `try` only wraps the JSON/`generated_at` parse. A top-level JSON array, a naive `generated_at` (`TypeError` on `now - at`), or a conflict entry missing `repo`/`number` (`KeyError` in the `parts` list comprehension) all raise outside the try instead of degrading to yellow.

**Simplest sufficient approach:** fix-forward on the existing worktree state, not a rewrite — every structural decision already there (constant placement, health-check shape, PR-card copy, write/truncate pattern, refuse-vs-clear for `decisions_submit.js`) is correct. Remaining work: the two must-fix defects, their two same-shape neighbors, one real design fork code review flagged twice, and tests the prior plan promised but never wrote.

**Tokens:** no new `gh` calls beyond the one extra read-only lookup per held ticket already accepted (now via `--paginate`, still one logical lookup, not per-page). Fixing six scoped bugs costs far less than re-deriving ~330 lines that mostly already passed review in spirit.

**Phone-OS / capability:** unchanged — a held ticket tells Gil the truth instead of silently losing feedback (#358's failure mode), and a label-conflict health check that's actually correct instead of a lookalike that drops data past page 1 and crashes on malformed input gives him a signal he can trust rather than one he'd have to read code to verify.

## Decisions

A genuine design fork code review raised and the prior attempt didn't resolve: `_label_conflicts` (`ticket_agents.py:291`) reports `held + needs-reengagement` as a conflict with the **same red severity** as `held + ready-for-agent` — but `plan_refeed` treats `held + needs-reengagement` as expected (skips it, no action), and `prState.js`'s own PR-card copy for that state is calm, not alarming. The ticket's "What to build" does say the health check should count and list both pairs, so dropping the pair outright would miss that — but equating a state the rest of this PR calls expected with a state that should never exist is the inconsistency code review flagged twice.

<!-- marvin:decisions -->
### conflict_severity: Should "held + needs-reengagement (sent back)" be red, same as "held + ready-for-agent"?
- [ ] A: Keep both pairs red — a held ticket should not be mid-rework either, regardless of which pair caused it.
- [ ] B: Downgrade "held + needs-reengagement" to yellow (still counted and listed, so AC1 still holds); keep "held + ready-for-agent" red, matching `plan_refeed`'s and `prState.js`'s existing treatment of that pair as expected and already handled.

## Tests to write first

No "How we'll try to break it" section exists on #455 (checked via `--json body`), so these are the standard misuse categories, corrected for the findings above. Items already correct in the current diff are kept as regression coverage, not rewritten.

**The two must-fix defects, with a regression test for each:**
1. Fix `test_write_label_conflicts_truncates_at_50` to take `tmp_path` and build its path from it — this *is* the test; it was broken, not missing.
2. `_hold_info` against a ticket with 35 synthetic events (mock `subprocess.run`: return one page unless `--paginate` is in argv, then return the full set) → finds the real latest hold event past page 1. Assert `--paginate` is present in both the events and comments calls.
3. `_hold_info` against events `labeled(hold, T1)`, `unlabeled(hold, T2)`, `labeled(held, T3)` → reports `since == T3`, `label == "held"`, not the stale `T1`/`"hold"` pair.
4. `_hold_info`/`status_for` with two currently-active hold labels whose events arrive in reverse-alphabetical order → the detail names the same label on repeated calls (determinism for the `sorted()` fix).

**The design-fork decision, tested against whichever answer Gil picks:**
5. `_label_conflicts` with `held` + `needs-reengagement` → conflict entry present either way (AC1 holds), with severity matching the Decision's answer via `check_label_conflicts`.

**Widened exception handling (the health-check-never-crashes gap):**
6. Top-level JSON array in the conflicts file → degrades to yellow, no `TypeError`.
7. Naive `generated_at` (no UTC offset) → degrades to yellow, no `TypeError` on `now - at`.
8. A conflict entry missing `repo` or `number` → renders as "unknown" or degrades the whole check to yellow, no `KeyError`.

**Already correct in the current diff, kept as regression coverage:**
9–17. `test_label_conflicts_detects_held_with_ready_for_agent`, `_detects_hold_with_needs_reengagement` (assertion changes only if answer is B), `_produces_two_entries_for_all_three_labels`, `_ignores_tickets_without_hold_labels`, `_detects_pinned_with_needs_reengagement`, `test_label_conflicts_are_written_with_metadata`, `test_write_label_conflicts_to_unwritable_path_silently_noop`, `test_refeed_does_not_touch_held_tickets_with_needs_reengagement`, `test_hold_labels_protect_tickets_from_triage`.
18–21. `test_check_label_conflicts_green/_red/_yellow_when_stale/_yellow_when_not_run_yet` — re-verify task 21 still passes once task 6–8's broader `except` lands (widening the catch must not change this test's expected message).
22–27. `rework_status`'s held-with/without-hold-info tests; dashboard's `decisions_submit.test.js`, `ticket_input.test.js`, `pr_state.test.js` held-ticket cases — all correct, kept.

**Each dependency failing:**
28. `_hold_info`'s comments call failing after the events call succeeds → still degrades gracefully (no direct test of `_hold_info` exists yet; tasks 2–4 are its first direct coverage — fold this in alongside them).

**Process check (not a unit test, a required step — same as the prior plan, still right: a self-contradicting test/message pair is exactly what a local run catches):** run `pytest lib/tests/` and the dashboard's `npm test` in full after every change, diffing actual failures against this list, not just the tests added for the two named bugs.

## Task List

1. **`lib/tests/test_ticket_agents.py`**: fix `test_write_label_conflicts_truncates_at_50` to take `tmp_path`, delete the hardcoded `/tmp/test_label_conflicts` directory creation (test 1).
2. **`lib/rework_status.py`**: rewrite `_hold_info` with `--paginate` on both `gh api` calls, `env=run_env()` (import from `project_catalog`, matching `ticket_agents._gh`), and per-label labeled/unlabeled tracking across the full event stream so `since`/`label`/`actor` reflect the currently-active hold episode (tests 2–3, 28).
3. **`lib/rework_status.py`**: `status_for`'s hold-label pick → `sorted(names & ticket_policy.HOLD_LABELS)[0]` with the same `"held"` fallback (test 4).
4. **Decision gate**: resolve `conflict_severity` before finalizing task 5's assertion — the PR carries the Decisions section and can't be approved until Gil answers it; `_label_conflicts`/`check_label_conflicts` severity for `held + needs-reengagement` follows the answer (test 5, and test 10 if the answer is B).
5. **`lib/health_checks.py`**: widen `check_label_conflicts`'s exception handling to cover the whole parse-and-render path (top-level-array, naive-datetime, missing-key), matching the file's own `except Exception` convention instead of the narrower tuple it shares with `check_hold_revisit` (tests 6–8). Re-run test 21 to confirm the "not checked yet" message/assertion pair still matches.
6. **`dashboard/electron/main/decisions_submit.js`**: replace the local `holdLabels` Set/`isHeld` with `import { isHeld } from '../../src/lib/hold_labels.js'`, matching the pattern already used by ten other files in this directory and by `ticket_input.js` for the same constant.
7. Run `pytest lib/tests/` and the dashboard's vitest suite in full after tasks 1–6; fix anything surfaced that this list didn't anticipate before calling the ticket done.
8. PR description: carry forward the refuse-vs-clear rationale from the original build (unchanged), state the two fixed must-fix defects and their two same-shape neighbors by file:line, link the Decisions answer once given, state this is a fix-forward, not a rewrite.
9. **Before this PR is opened or any automated run is dispatched against #455, re-check that `hold` has been removed by Gil.** As of this plan it is still present, with his most recent comment explicitly asking for its removal before requeueing. If it's still there when this task list would otherwise run, that's the stop condition this ticket exists to create — stop, don't proceed around it again.