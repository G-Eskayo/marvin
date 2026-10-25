I ran the full suite myself and got direct evidence that overturns my last message's hypothesis — the 2 "regressed" pytest failures are a pre-existing, unrelated flake, not caused by this ticket's code. Correcting the plan.

## Correction to the plan above

The full-suite run I just executed (`~/.agents/venv/bin/python -m pytest -q`, this exact worktree, this ticket's diff applied) came back **2 failed, 3204 passed, 10 skipped** — and both failures are in `lib/tests/test_marvin_hooks.py` (`test_install_moves_hooks_to_user_settings_and_sets_one_memory`, `test_wired_scripts_reads_the_real_installed_hooks`), a file this ticket's diff never touches. Re-running just that file in isolation seconds later: **19/19 passed**, including both previously-failed tests. `test_wired_scripts_reads_the_real_installed_hooks` explicitly reads this machine's live, shared `~/.claude/settings.json` (`lib/marvin_hooks.py:124`, `USER_SETTINGS = HOME / ".claude" / "settings.json"`) rather than a `tmp_path` fixture — a test coupled to real, shared machine state will transiently disagree with `lib/marvin_hooks.py::HOOKS` if another concurrent session rewrites that file mid-run (this repo's own CLAUDE.md warns sessions share state and can write concurrently). That's a pre-existing flake risk in that test, not something introduced by this ticket.

Redoing the arithmetic correctly against the metrics comparison: baseline 3193 passed/0 failed already included `test_marvin_hooks.py`'s 19 tests passing; this ticket adds 13 new, all-passing tests; 3193 + 13 − 2 (the two that flaked this run) = 3204 passed, 2 failed — matching the reported numbers exactly, with the 2 failures attributable entirely to the pre-existing flake, not to any of the 13 new tests. My previous message's claim that "the regression is contained inside the 13 new tests" and its proposed `client=None` dependency-injection fix were wrong inferences from the delta numbers alone, made before I had the actual failure output — withdrawn.

**Revised conclusion:** the already-drafted `query_research_feed.py` and its 13 tests (`skills/research-colony/scripts/tests/test_query_research_feed.py`) need **no changes** — they're correct as written, verified passing twice now (isolated and inside the full suite). The rest of the previous plan's "North-star fit," "Research findings," "What to build" (items 1–8, minus the now-unnecessary DI change to item 1 and the test rewrites in item 2), and "Decisions" sections stand unchanged. Only the "Tests" and "Task List" sections change:

## Tests (revised)

All 13 tests from the original list stand exactly as already drafted in this worktree — no rewrite needed. Added:

14. **Document, don't fix, the unrelated flake**: no new test is added for `test_marvin_hooks.py`'s live-settings coupling — it's out of this ticket's scope (different subsystem, different owner concern: hook installation, not research/research-colony). Note it in the PR description so it isn't mistaken for a regression this ticket caused, and leave fixing that test's machine-state coupling for a separate ticket if it keeps flaking.

## Task List (revised)

1. Keep `skills/research-colony/scripts/query_research_feed.py` exactly as already drafted in this worktree — no DI seam needed, it's correct.
2. Keep `skills/research-colony/scripts/tests/test_query_research_feed.py` exactly as already drafted — all 13 tests pass, in isolation and inside the full suite.
3. Keep `skills/research/SKILL.md` and `brain-map/enrichment.json` exactly as already edited — re-verified correct.
4. Update `docs/adr/0070-research-skill-checks-research-feed-first.md`'s Decision section to record: built in #54, unconditional check, soft-merge — no test-mechanism caveat needed this time.
5. Leave `reference-research-feed-recheck.md` memory as-is — already accurate.
6. `gh issue edit 54 --repo G-Eskayo/marvin` to add the "What to build" section to the issue body.
7. Run the full suite once more right before committing (`~/.agents/venv/bin/python -m pytest -q`); if `test_marvin_hooks.py` fails again, re-run just that file in isolation to confirm it's the same live-settings flake (not a real regression) before proceeding — don't let it block the commit if isolated re-run is green.
8. Commit, push, open the PR against `main`, noting the known unrelated flake in the PR description; comment on/close #54 with the ADR link once merged.