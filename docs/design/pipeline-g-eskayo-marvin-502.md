## North-star fit

Reuses the existing longest-key-first pattern already in the codebase: `lib/support.py:770` (`_redact`) does exactly `sorted({w for w in words if w}, key=len, reverse=True)` to make a longer match win over a shorter substring — the same shape the ticket asks for in `extract_project`/`find_project_path`. (`qa_session_capture.py`'s separate `extract_project`, lines 63-74, dodges the same shadowing bug today only by hand-ordering a hardcoded tuple — that's not a reusable pattern, just evidence the bug is real and recurring; it's out of scope here since the ticket only names `improvement_sweep.py`.) This is the simplest sufficient fix: change the iteration order in two existing loops, no new data structure, no new file. It spends a handful of tokens on two one-line loop-header edits plus tests; it saves resources per north star 1 by making the sweep scan `~/.agents/bench` instead of all of `~/.agents` for every `marvin-bench` handoff (smaller, faster, less noisy top-5). It leaves the user more capable: the bench backlog starts actually accumulating real findings under its own heading instead of being silently folded into marvin's, with no ongoing attention needed from Gil.

The ticket doesn't state its own "reuses X" fit beyond "Match longer keys first in both lookup loops" — checked against the code, that's accurate; `lib/support.py:770` is the concrete precedent it's implicitly following.

## Current state read

- `skills/improve/scripts/improvement_sweep.py:52-60` — `find_project_path`: `for key, path in KNOWN_PROJECTS.items():` then `if key in low and path.exists(): return path`.
- `skills/improve/scripts/improvement_sweep.py:63-72` — `extract_project`: `for name in KNOWN_PROJECTS:` then `if name in snippet: return name`.
- `KNOWN_PROJECTS` (lines 42-49) is a 6-entry dict; `"marvin"` is a substring of `"marvin-bench"` and currently sorts first by insertion order.
- `skills/improve/scripts/tests/test_improvement_sweep.py` already has `test_known_project_paths_point_where_the_projects_actually_live` (checks dict values only, not resolution — the gap the ticket calls out) and no existing test calls `extract_project` or `find_project_path` directly.

## Tests to write first

One per "How we'll try to break it" case, plus the acceptance-criteria assertions, plus misuse the section didn't cover:

1. `extract_project("## What we were working on\nmarvin-bench Run 31 holdout\n") == "marvin-bench"` — longer key wins over its own prefix (acceptance criterion 1, break-it case "text naming both").
2. `find_project_path("marvin-bench")` returns `~/.agents/bench`, with `KNOWN_PROJECTS` monkeypatched to a dict of tmp paths that actually exist (acceptance criterion 2).
3. `find_project_path` falls through to the next-longest match when the longest key's path doesn't exist (break-it case: "`marvin-bench` key whose path does not exist... falls through rather than returning a missing path") — patch `KNOWN_PROJECTS` with `"marvin-bench"` pointing at a non-existent tmp path and `"marvin"` at one that exists; expect the `marvin` path back, not `None`.
4. Mixed case `"Marvin-Bench"` still matches `marvin-bench` in both `extract_project` and `find_project_path` (break-it case: both already lowercase first — confirm the fix doesn't disturb that).
5. Plain `"marvin"` text (no `-bench` suffix) still resolves to `"marvin"` through `extract_project`, and `find_project_path("marvin")` still returns `~/.agents` (acceptance criterion 3, first half).
6. Unknown/unrecognized text returns `"session"` from `extract_project`, and `find_project_path` of made-up text returns `None` when no `~/<name>` fallback directory exists either (acceptance criterion 3, second half — covers the empty/garbage-input misuse case explicitly).
7. Empty-string input: `extract_project("")` returns `"session"` (no `## What we were working on` section at all) — bad/empty-input misuse case not named by the ticket.
8. A string containing none of the `KNOWN_PROJECTS` keys but matching the `Path.home() / project_name` fallback in `find_project_path` still resolves via that fallback, unaffected by the sort-order change (regression guard on the existing fallback branch, since the loop restructuring touches code right above it).

No new dependency, no concurrency, no permissions angle, and nothing network/IO-failing here — `find_project_path`/`extract_project` are pure functions over a dict and a string, so the "each dependency failing" / "repeats and concurrency" / "wrong permissions" misuse categories from the north stars don't apply to this unit; they're already covered elsewhere for the hook's I/O (file read, safety-monitor, inbox) by the existing tests in this file, which this change doesn't touch.

## Decisions

None. The ticket is fully specified (`ready-for-agent`), the fix is mechanical, and no design option is open.

## Task List

1. In `skills/improve/scripts/improvement_sweep.py`, change `find_project_path` (line 54) to iterate `sorted(KNOWN_PROJECTS.items(), key=lambda kv: len(kv[0]), reverse=True)` instead of `KNOWN_PROJECTS.items()`.
2. In the same file, change `extract_project` (line 69) to iterate `sorted(KNOWN_PROJECTS, key=len, reverse=True)` instead of `KNOWN_PROJECTS`.
3. Add the 8 tests above to `skills/improve/scripts/tests/test_improvement_sweep.py` (new tests only; the existing `test_known_project_paths_point_where_the_projects_actually_live` and all dedup/inbox tests stay as-is since they don't touch resolution order).
4. Run `~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_improvement_sweep.py -v` and confirm all tests (old and new) pass.