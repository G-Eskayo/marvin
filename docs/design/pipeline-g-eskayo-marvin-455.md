Good, confirms the `_result(id, label, severity, detail, value=None)` signature already used in my design. I have everything needed to write the final plan now.

## North-star fit

**Reuses, before adding anything new:**
- `check_missing_profiles`'s `snapshot=None → collect via injected gh` shape (`lib/health_checks.py:612-623`, proven by `test_missing_profiles_snapshot_passed_directly`, `lib/tests/test_health_checks.py:484-499`) is the one established pattern for a health check that reads tickets without hitting GitHub directly. `check_contradictory_hold_labels` (`lib/health_checks.py:643-684`) is the only thing in this diff that still doesn't follow it — it ignores `snapshot`/`gh` and always calls `tp._open_issues(repo)` wrapped in a bare `except Exception: pass` that swallows both per-issue malformations and whole-repo GitHub failures alike. This is exactly what the last code review flagged. Fix: delete the `tp._open_issues` call, build `snapshot` via `ticket_agents.collect(repos, gh=gh or ticket_agents._gh)` exactly like `check_missing_profiles` does, and iterate the resulting `{repo: {"issues": [...], "prs": [...]}}` shape directly.
- `ticket_policy.HOLD_LABELS` (`lib/ticket_policy.py:16`, already the one definition of "a person's hands off") stays as-is — the fix is only to stop treating two hold labels together (`hold`+`held`) as a reportable contradiction. Only a hold label *co-occurring with* a pipeline label (`ready-for-agent` or `needs-reengagement`) is the actual #358 scenario, and that's the only thing flagged after this fix.
- **Everything else the ticket asks for is already built correctly in this worktree** and just needs tests, not new code: `lib/rework_status.py`'s `_gh`/`_latest_hold_event`/`_comment_near`/`_hold_info`/`status_for` (held branch with who/when/comment) and `collect()` (fetches hold info only for tickets whose labels intersect `HOLD_LABELS`); `ticket_policy.HOLD_LABELS` + `triage_verdict`'s guard; `ticket_agents.plan_refeed`'s `names & pol.HOLD_LABELS` guard; `ticket_pipeline.HOLD_LABELS = ticket_policy.HOLD_LABELS`; `decisions_submit.js`'s `isHeld`/`heldNote` branch (refuse, don't auto-remove — same choice as the prior attempt, still the right one); `prState.js`'s held-rework detail. Re-reading each confirms correctness; I'm not touching any of them.
- `check_hold_revisit`'s 5-card-cap + "+N more" convention (`lib/health_checks.py:480-499`) is kept exactly as implemented, only the test coverage is being corrected to match the new label-pair definition.

**Why this is the simplest sufficient approach:** the only remaining defect is one function with a wrong data-access pattern and a wrong label-pair rule. No new mechanism, label, service, or file. Everything else the review didn't flag is read-but-unchanged.

**Where it spends tokens:** nothing new — same two conditional `gh` calls per held+sent-back ticket as before, now reached through the gate (`run_env()`) instead of a bare `subprocess.run`.

**More capable or more passive:** more capable — Gil's health tab now catches the real contradiction (hold + ready-for-agent/needs-reengagement) instead of a redundant one (hold + held) that isn't actually a problem, and a malformed issue from one repo no longer silently blanks out every finding for that repo.

**No Decisions section.** Checked `docs/adr/` and `CONTEXT.md` for anything about `HOLD_LABELS`, hold-label contradictions, or "refuse vs. auto-remove": nothing contradicts the prior attempt's choice (refuse, mirroring how `claimed:*` labels are already handled — explicit removal only, no timeout). Nothing here needs the owner to choose.

## Tests (written first)

**`lib/tests/test_health_checks.py`** (rewriting the 3 existing hold-contradiction tests, which assert the wrong behavior or bypass `snapshot`, plus new ones):
1. Rewrite `test_check_contradictory_hold_labels_detects_multiple_hold_labels` → rename/repurpose: `hold`+`held` alone, passed via direct `snapshot={"test/repo": {"issues": [...]}}` (no `gh`/`tp` involved) → **not** reported (fix_these #2).
2. Rewrite `test_check_contradictory_hold_labels_detects_hold_with_pipeline_labels` to use a direct `snapshot=` instead of monkeypatching `tp._open_issues`: `hold`+`ready-for-agent`, `held`+`needs-reengagement`, `pinned`+`ready-for-agent` all reported; a plain `ready-for-agent`-only ticket is not.
3. Rewrite `test_check_contradictory_hold_labels_caps_at_5_plus_summary` the same way (direct `snapshot`, 10 contradictory tickets → 5 cards + 1 "+5 more").
4. New: boundary — a ticket with only a hold label, or only a pipeline label, in the same snapshot → not reported (not "any hold-ish label present").
5. New: a malformed issue (non-dict entry in `issues`, or an issue dict missing `labels` entirely, or `labels: None`) doesn't crash the check and isn't counted — but a *different*, well-formed, contradictory issue in the **same repo's list** is still found (the must-fix: one bad issue must not blank the whole repo).
6. New, direct regression for fix_these #1: `check_contradictory_hold_labels(snapshot={}, repos=["test/repo"])` with `ticket_agents.board_repos`/`ticket_agents.collect` monkeypatched to raise/record calls → assert neither is called, and no `tp._open_issues` call happens either (mirrors `test_missing_profiles_snapshot_passed_directly`).
7. New: `snapshot=None`, `ticket_agents.board_repos`/`collect`/`_gh` monkeypatched exactly like `test_missing_profiles_red_when_ready_tickets_but_no_profile` → the injected snapshot is actually read and a contradiction in it is found (end-to-end for the `snapshot is None` branch, not just "doesn't crash").
8. New: `snapshot=None`, `board_repos` returns `[]` → `[]`, and `collect`/`_gh` are never called (empty-repos short-circuit, symmetric with `check_missing_profiles`'s `test_missing_profiles_empty_when_no_repos`).

**`lib/tests/test_rework_status.py`** (code already correct; these close the untested paths that let the prior defects ship):
9. `_hold_info` with a fake `gh` that raises on the events call → `None`, no exception.
10. `_hold_info` with a fake `gh` returning malformed/non-JSON stdout on the events call → `None`.
11. `_hold_info` with a fake `gh` returning no hold-label line (empty/garbage stdout) → `None`.
12. `_hold_info`: events call succeeds, comments call independently raises → still returns `{who, when}`, `comment` is `None`.
13. `_hold_info`: malformed comment data — `comments` not a list, an entry missing `createdAt`/`body`, a non-dict entry — doesn't crash, `comment` stays `None`.
14. `collect()`: a sent-back ticket that is **not** held costs zero `_hold_info` calls (call-count assertion on a monkeypatched `_hold_info`).
15. `collect()` end-to-end: a held + sent-back fixture produces `"state": "held"` with a populated `detail` (extends `test_collect_reads_each_projects_open_issues_once`'s fake-`subprocess.run` pattern).

**`lib/tests/test_ticket_agents.py`** (code already correct, untested):
16. `plan_refeed` on a `needs-reengagement` ticket that also carries `hold` → no actions. Parametrize over `held`/`pinned` too, proving the guard uses the full `HOLD_LABELS` set.
17. Regression: a plain `needs-reengagement` ticket (no hold label) is still refed (existing coverage at `lib/tests/test_ticket_agents.py:128`, re-asserted unchanged).

**`dashboard/test/decisions_submit.test.js`** (code already correct, untested):
18. A `needs-info` ticket that also carries `hold` (parametrize `held`/`pinned`), every decision answered → `exec` is never called with `--add-label ready-for-agent`; result carries `heldNote`.
19. Regression: a plain `needs-info` ticket with no hold label still moves to `ready-for-agent` (existing test, line 205, stays passing unchanged).

**`dashboard/test/decisions_view.test.jsx`**:
20. `status.result.heldNote` set → the held note renders in the submitted state.

**`dashboard/test/pr_state.test.js`** (code already correct, untested):
21. `sentBack: true` + `rework: {state: 'held', ...}` → detail mentions the hold, and does **not** contain "a reworked version will update" (acceptance criterion 3, literal negative assertion).
22. Regression: `sentBack: true` + `rework: null` or `rework: {state: 'queued'}` → unchanged generic sent-back sentence.

No case from the issue's body repeats verbatim (it has no "How we'll try to break it" section); the list above covers the standard misuse categories scoped to what's touched: each dependency (`gh` events call, `gh` comments call, `ticket_agents.collect`) failing independently, malformed/huge data from GitHub, a non-dict/missing-field issue from a hand-edited label, repeats via `collect()`'s call-count check, and a person's mistake via hand-added contradictory labels. Nothing here is newly outward-facing.

## Task List

1. `lib/health_checks.py`: rewrite `check_contradictory_hold_labels(snapshot=None, repos=None, gh=None)` — when `snapshot is None`, build it via `ticket_agents.collect(repos, gh=gh or ticket_agents._gh)` after the existing `repos = repos or ticket_agents.board_repos(); if not repos: return []` guard (mirrors `check_missing_profiles`); iterate `snapshot.items()` → `data.get("issues") or []`, skip non-dict issue entries; flag only `HOLD_LABELS ∩ names` together with `{"ready-for-agent", "needs-reengagement"} ∩ names` (drop the "two hold labels" case); drop the `tp`/bare-`except` wrapper entirely; keep the existing 5-card + "+N more" cap unchanged.
2. Rewrite the 3 existing hold-contradiction tests in `lib/tests/test_health_checks.py` to use direct `snapshot=` fixtures instead of monkeypatching `tp._open_issues`, and correct the hold+held assertion (tests 1-3 above).
3. Add the new `test_health_checks.py` cases: boundary, malformed-issue isolation, snapshot-passed-directly regression, snapshot=None end-to-end, empty-repos short-circuit (tests 4-8).
4. Add the new `test_rework_status.py` cases for `_hold_info`'s untested failure/malformed-data paths and `collect()`'s call-count/end-to-end behavior (tests 9-15) — no production code change expected here; if any of these fail against the current code, fix the minimal gap, don't rewrite what's already correct.
5. Add the new `test_ticket_agents.py` parametrized hold-label cases for `plan_refeed` (tests 16-17) — no production code change expected.
6. Add the new `decisions_submit.test.js` parametrized hold-label cases (tests 18-19) and the one `decisions_view.test.jsx` render test (test 20) — no production code change expected.
7. Add the new `pr_state.test.js` held-detail cases (tests 21-22) — no production code change expected.
8. Delete `PR_BODY.md` from the worktree (untracked, describes work not in the diff and a fix that wasn't actually applied) — do not recreate it until the PR is actually ready to open, and don't commit it then either.
9. Run `pytest lib/tests/test_health_checks.py lib/tests/test_rework_status.py lib/tests/test_ticket_agents.py lib/tests/test_ticket_policy.py`, then `vitest` for `decisions_submit.test.js`, `decisions_view.test.jsx`, `pr_state.test.js`, then the full `pytest lib/tests/` and full `vitest` suites to confirm no regressions.
10. Draft the final PR body at open time (not as a committed worktree file) naming: the refuse-not-auto-remove decision, the three must-fix defects from the last review and how each was fixed, and which parts of the ticket were already correct in this worktree before this pass.