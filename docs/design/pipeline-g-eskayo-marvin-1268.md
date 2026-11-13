## North-star fit

Reuses `lib/resume_check.py`'s existing `ranked_handoffs()` (resume_check.py:122, already imported) and `resume_prompt()` (resume_check.py:129, already imported) — no new matching/ranking logic, just removing a bad default override and walking an already-returned list. The local `_surface_resume_prompt()` helper (`check_remote_session.py:89`) is reused unchanged. This matches the ticket's own stated fit and I confirm it against the code: `generate_handoff_from_transcript.py:107` does write `handoff-{now:%Y-%m-%d-%H-%M}` (confirmed by reading the file), so the library default `handoff-*.md` is correct and the `pattern="*.md"` override at `check_remote_session.py:161` is simply wrong. No new file, no new abstraction — a one-line pattern fix plus a bounded loop over a list already in memory, so token/compute cost is unchanged. It serves north star 2 (nothing breaks silently): today, a stale notes file or a promptless handoff can either relay wrong "current" context or silently give nothing; after the fix the user always gets either the right resume prompt or a clear one-line reason why not — more capable, not more passive, at the exact moment (arrival on a new machine) this hook exists for.

Test reuse: the existing `remote` fixture and `_load()` helper in `lib/tests/test_resume_check_wiring.py` (lines 31–36, 93–103) are reused for every new test below — no new test harness.

One existing test needs updating, not just new ones: `test_the_surfaced_handoff_is_chosen_by_as_of` (`lib/tests/test_resume_check_wiring.py:167`) currently writes two `handoff-*.md` files with **no** `## Resume prompt` section at all. Under the fix, neither would qualify, the loop would find nothing, and the test's assertion (`picked == ["handoff-a.md"]`) would fail — not because the fix is wrong, but because the test no longer models a real "both qualify, newer wins" case. It must be updated to give both files a resume prompt so it still exercises as-of ranking among qualifying candidates (this matches the closed PR #1284's own note that this test "now writes files that carry prompts" — I verified that's required by reading the current file, not by trusting the old PR's claim).

No Decisions section: the ticket is fully specified (`ready-for-agent`), the owner already settled the one open design question in the comments ("build in-house, don't copy #1284's code"), and nothing here requires the owner to pick between options.

One acceptance item is not a code change: "`sort_suggestions.py` has been run after this change lands to re-sort `~/.claude/suggestions.md`" acts on the live `~/.claude` directory, outside this repo/worktree. It's a one-time housekeeping command, not a diff — listed last in the task list, to run once the code change is committed.

## Tests to write first (in `lib/tests/test_resume_check_wiring.py`, reusing the `remote` fixture / `_load` helper)

1. **Update** `test_the_surfaced_handoff_is_chosen_by_as_of` — give both `handoff-a.md` and `handoff-b.md` a `## Resume prompt` body so the as-of ranking is still meaningfully exercised post-fix (acceptance criteria overlap; existing-test regression guard).
2. A newer `notes-*.md` (no resume prompt, newest mtime) sits next to an older `handoff-*.md` that has one → the handoff is surfaced, not the notes file. (acceptance criterion 1 / the pattern bug)
3. The newest `handoff-*.md` has an empty `## Resume prompt` (whitespace/dashes only, exercising `resume_check.resume_prompt`'s own stripping) → the next-ranked handoff that has a real prompt is surfaced instead. (acceptance criterion 2)
4. No candidate anywhere has a resume prompt → the labelled fallback line prints (containing the device id and "no resume prompt in handoffs/"), `_surface_resume_prompt` is never called, and `mod.main()` does not raise. (acceptance criterion 3)
5. An undated non-handoff file (e.g. `2026-10-21-pipeline-fixes-in-flight.md`) that *does* carry a prompt-shaped `## Resume prompt` heading is still excluded, proving exclusion comes from the `handoff-*.md` glob, not the prompt check — and with no `handoff-*.md` present, the fallback line from test 4 is what prints. (acceptance criterion 4)
6. Misuse not explicitly listed: one ranked candidate's file disappears/raises `OSError` on read between the glob and the read (stale state) → the walk skips it and still picks the next qualifying candidate, without crashing.

## Task List

1. In `skills/handoff/scripts/check_remote_session.py`, drop the `pattern="*.md"` argument from the `resume_check.ranked_handoffs(...)` call at line 161 so the library default `handoff-*.md` applies.
2. Replace the `if ranked: _surface_resume_prompt(ranked[0][0])` block with a loop over `ranked` that reads each candidate (skipping any that raise `OSError`) and picks the first whose `resume_check.resume_prompt(text)` is non-empty.
3. When no candidate qualifies, print one labelled line (e.g. `f"rebuilt a handoff on {device_id} but found no resume prompt in handoffs/"`) instead of returning silently.
4. Update `test_the_surfaced_handoff_is_chosen_by_as_of` in `lib/tests/test_resume_check_wiring.py` so both fixture handoffs carry a resume prompt.
5. Add the five new tests listed above (items 2–6 in the tests-first list) to `lib/tests/test_resume_check_wiring.py`, reusing the `remote` fixture.
6. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_resume_check_wiring.py lib/tests/test_check_remote_session.py lib/tests/test_resume_check.py -v` and confirm all pass, including the unmodified existing tests in those files.
7. Run `~/.agents/skills/architecture-review/scripts/sort_suggestions.py` once the code change is committed, to re-sort `~/.claude/suggestions.md` per acceptance criteria.