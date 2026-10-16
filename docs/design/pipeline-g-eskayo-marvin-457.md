Have everything needed. Writing the revised plan now.

## North-star fit

**Reuses:** the implementation from the prior attempt is already in this worktree, uncommitted (`lib/main_health.py`, `lib/health_checks.py`, `dashboard/electron/main/boot_data.js`, and all three test files already carry the lock/skip-list/carry-forward machinery). This plan does **not** redo that work — it patches the four defects code review found in it, plus a regression test for each, and otherwise leaves the design (atomic `O_CREAT|O_EXCL` lock, PID/age staleness, `fnmatch` skip-list, carried-verdict JSON fields) untouched. Re-deriving the whole thing again would burn tokens re-proving ground the last attempt already covered correctly (19 of 19 behavioral tests pass; `pytest`/`vitest` deltas are net positive).

**Simplest sufficient approach:** three one-line/few-line code changes (a regex, an `except` tuple, a `mkdir`) and one test-hygiene fix (stop binding to the real `~/.agents` repo by default) — no new abstractions, no new files.

**Tokens/compute:** this is strictly a bug-fix pass, pure local compute (regex, exception handling, `mkdir`, subprocess calls in tests). No LLM calls at runtime in the changed code.

**User capability:** closes the gaps that made the fix itself unreliable on exactly the conditions it was built to survive — a fresh machine with no `~/.claude/logs` yet, a missing `~/.agents` checkout, launchd's stripped `PATH`. Infrastructure reliability; no judgment taken from Gil.

## Decisions

None needed. All four findings are mechanical bug fixes with one correct answer each (a tighter regex, a wider `except` tuple, creating a directory before writing into it, and not depending on the real `~/.agents` repo's git history in a unit test). No design choice is open.

## Tests first

Each targets one must-fix finding; existing 19 tests are kept and re-verified unmodified except where noted.

**`dashboard/test/boot_data.test.js`** (fixes finding 1 — `boot_data.js:98`):
1. Replace the existing loose match at line 182 (`toMatch(/CARRIED FROM DEF5678/)`) with an **exact** string assertion on the full TEST chip text for a detail of `"main @ abc1234 (carried from def5678): 2143 passed, 9 skipped"`. Expected: `'TESTS · 2143 PASSED · 9 SKIPPED · CARRIED FROM DEF5678'` — i.e. no trailing `):` or `)` leaking into the marker. This fails against the current `/carried from (\S+)/` regex (it would produce `...CARRIED FROM DEF5678):`) and passes once the regex becomes `/carried from ([^\s):]+)/`.

**`lib/tests/test_main_health.py`** (fixes findings 2, 3, 4):
2. `test_changed_paths_handles_missing_git_or_repo` — call `mh._changed_paths("a", "b", repo_dir=tmp_path / "does-not-exist")`. Today this raises `FileNotFoundError` uncaught (not caught by `(CalledProcessError, TimeoutExpired)`); must return `None` instead. Covers "git not on PATH" / "repo dir missing" from the docstring's own "fail safe" promise.
3. `test_acquire_lock_creates_missing_parent_directory` — call `mh._acquire_lock(tmp_path / "fresh-machine" / "logs" / "m.lock", os.getpid(), NOW)` where `fresh-machine/logs` does not exist. Today this raises `FileNotFoundError` from `os.open`; must succeed and leave the lock file written. Also run the matching `refresh()`-level case: `mh.refresh(state_path=..., lock_path=tmp_path / "missing" / "m.lock", ...)` completes with `ran: True` rather than silently returning `ran: False` forever.
4. Fix the three tests identified by review to stop depending on the real `~/.agents` repo:
   - `test_single_flight_concurrent_calls_skip_while_one_is_running`: pass `changed_paths=lambda *a, **k: None` to both the init call and `thread1`'s `refresh()` call (the real behavior under test is the lock, not the skip-list).
   - `test_lock_is_released_after_success`: pass `changed_paths=lambda *a, **k: None` to the second `refresh()` call.
   - `test_exception_during_suite_leaves_state_untouched`: pass `changed_paths=lambda *a, **k: None` to the second `refresh()` call.
   - Add one assertion-bearing regression test, `test_changed_paths_is_never_called_against_the_real_repo_by_default_in_tests`, that greps `test_main_health.py` itself for any `mh.refresh(` call lacking an explicit `changed_paths=` argument when a prior sha is already recorded — catches this exact class of leak if it recurs. (Lightweight: a static check within the test file, not a new fixture.)

All other existing tests in the three files are re-run unmodified to confirm no regression (the 16 non-listed `test_main_health.py` cases, the `check_main_health` pair in `test_health_checks.py`, and the other `boot_data.test.js` TEST-line case).

## Task List

1. `dashboard/electron/main/boot_data.js:98` — change `t.detail.match(/carried from (\S+)/)` to `t.detail.match(/carried from ([^\s):]+)/)`.
2. `dashboard/test/boot_data.test.js` — tighten the carried-from test (line ~176-186) to an exact `toBe(...)` on the full chip text instead of a loose `toMatch`.
3. `lib/main_health.py:_changed_paths` (~line 135) — widen `except (subprocess.CalledProcessError, subprocess.TimeoutExpired):` to also catch `OSError` (covers `FileNotFoundError` for a missing repo dir or `git` not on `PATH`).
4. `lib/main_health.py:_acquire_lock` (~line 78) — add `lock_path.parent.mkdir(parents=True, exist_ok=True)` before the first `os.open` call.
5. `lib/tests/test_main_health.py` — add `test_changed_paths_handles_missing_git_or_repo` and `test_acquire_lock_creates_missing_parent_directory` (+ a `refresh()`-level variant).
6. `lib/tests/test_main_health.py` — inject `changed_paths=lambda *a, **k: None` into the three identified calls in `test_single_flight_concurrent_calls_skip_while_one_is_running`, `test_lock_is_released_after_success`, `test_exception_during_suite_leaves_state_untouched`.
7. Run `lib/tests` (pytest) and the dashboard vitest suite; confirm all green, including the 5 new/changed tests failing against the pre-fix code and passing after.
8. Diff-review the four production-code edits against the four review findings one-to-one before committing — no unrelated changes.