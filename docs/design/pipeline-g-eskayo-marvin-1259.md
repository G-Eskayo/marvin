## North-star fit

**Reuses:** `lib/commit_check.py:33,126` already does exactly what `lib/affected_tests.py` should do — `import test_change_rule as tcr; tcr.kind(c["path"], tcr.MARVIN_RULES)` — so the gate's verify step and the direct-commit check can never disagree (per `test_change_rule.py`'s own docstring). `lib/affected_tests.py` is the one place still rolling its own classifier (`_TEST` regex), which is the actual bug: a second source of truth that silently drifted from the first. The fix is to make it import and reuse `test_change_rule.kind()`/`MARVIN_RULES` too, not to add a new classification system.

**Simplest sufficient approach:** delete two bad glob patterns, add one precise one (`brain-map/scripts/test_*.py`), and make `affected_tests.all_tests()` require `tcr.kind(p, tcr.MARVIN_RULES) != "code"` in addition to its existing name-regex filter — a one-line intersection, not a rewrite. (Fully swapping the regex for `kind()` alone would wrongly start selecting `lib/tests/conftest.py` as a runnable test, since `lib/tests/**` matches it but pytest can't collect it — the existing acceptance test `test_selection_never_returns_a_file_pytest_would_not_collect` would catch that regression, confirming the intersection is the right shape, not scope creep.)

**Tokens:** spends a few tokens now fixing a one-line rule table; saves far more later — this is the gate that is supposed to catch a code change merging without a test, so a hole in it compounds into silent breakage across every future PR that happens to touch `lib/test_slot.py` or `lib/test_change_rule.py`.

**Capability:** leaves the user (Gil) more protected, not more passive — it's pure gate-hardening, no new surface for him to operate.

**Correction to the ticket's own stated fit:** none needed — its north-star fit (reuse the `tests/`-directory convention, one rule fix protects all future merges) matches what's actually in the code.

## Tests to write first

In `lib/tests/test_test_change_rule.py` (extends the existing file, same pattern as its other assertions):

1. `kind("lib/test_slot.py", R) == "code"` and `kind("lib/test_change_rule.py", R) == "code"` (acceptance criterion).
2. `kind("brain-map/scripts/test_facts.py", R) == "test"` (acceptance criterion).
3. `kind("skills/x/scripts/tests/test_x.py", R) == "test"` and `kind("tests/test_machine_resources.py", R) == "test"` (ticket's break-it cases 2/3 — these already pass today via the `**/tests/**` special-case in `_match`; locking them in as a regression guard).
4. `kind("lib/test_something.py", R) == "code"` (break-it case 1 — a new production module named like a test).
5. `check([ch("lib/test_slot.py")], R)` fails, and `check([ch("lib/a.py"), ch("lib/test_slot.py")], R)` fails (acceptance criteria).
6. `check([ch("lib/test_slot.py"), ch("lib/tests/test_something.py")], R)` **passes** (break-it case 4: real test present alongside the now-code file).
7. `kind("./lib/test_slot.py", R) == "code"` and `kind("/lib/test_slot.py", R) == "code"` (break-it case 5 — `./` and leading-`/` prefixes must classify the same; today they don't, because `lib/**` requires a literal prefix match with no normalization, so this is a real gap, not a hypothetical).
8. Guard test: `for p in sorted(Path(repo_root).glob("lib/*.py")): assert kind(f"lib/{p.name}", R) == "code"` — walks the real top-level `lib/*.py`, including `test_slot.py` and `test_change_rule.py` themselves (acceptance criterion).

In `lib/tests/test_affected_tests.py` (extends the existing fixture-repo pattern):

9. A file named like a test that is really code does not select itself, and its real test does: write `lib/test_widget.py` + `lib/tests/test_test_widget.py` (which imports it) into the fixture repo, change `lib/test_widget.py`, assert `"lib/test_widget.py" not in at.select(...)` and `"lib/tests/test_test_widget.py" in at.select(...)` (acceptance criterion: "no longer selects `lib/test_slot.py`/`lib/test_change_rule.py` as tests, selects their real tests instead" — proven with an equivalent fixture rather than depending on the real `lib/test_slot.py`’s current import graph).

Verification (not new tests, run against the real suites per the acceptance criteria):
- `pytest --collect-only -q lib | rg 'lib/test_(slot|change_rule)\.py'` — confirm it returns nothing before deciding pytest.ini needs no change (per the ticket's own closing note).
- Full `lib/` and `brain-map/scripts/` suites pass.

No misuse cases beyond the ticket's own list are missing: empty/huge/malformed-path handling, dependency failure, concurrency, and stale-state are already covered by existing tests in both files (`test_a_huge_diff_is_handled`, `test_an_unreadable_worktree_fails_closed`, etc.) and are untouched by this change.

## Decisions

None — the ticket's "What to build" fully specifies the rule list and the classification reuse; nothing here needs Gil to choose between options.

One scope call I'm making myself, not deferring: the "Recurrence check" section's probe ("count merged PRs that changed `lib/*.py` with no test change") is not in the acceptance criteria, and the guard test (item 8 above) is the check the ticket itself says is sufficient ("none yet: the guard test is the check"). I'm leaving the probe out of this PR to avoid scope creep beyond the stated acceptance criteria; it's a reasonable candidate for a follow-up ticket if Gil wants trend data on it.

## Task List

1. In `lib/test_change_rule.py`: replace `MARVIN_RULES["test"]`'s `"**/test_*.py", "**/*_test.py"` with `"brain-map/scripts/test_*.py"`, keeping `lib/tests/**`, `dashboard/test/**`, `**/tests/**`, `**/*.test.*`, `**/*.spec.*`. Leave `DEFAULT_RULES` untouched.
2. In `lib/test_change_rule.py`'s `kind()`: strip a leading `./` and leading `/` from `path` before matching, so prefix variants classify identically.
3. In `lib/tests/test_test_change_rule.py`: add the assertions listed in tests 1–8 above (extend `test_paths_are_code_tests_or_other`, add a new `test_every_top_level_lib_module_is_code`, extend the `check()` test cases, add the `./`/leading-`/` cases).
4. In `lib/affected_tests.py`: `import test_change_rule as tcr` at module load, and change `all_tests()` to `return sorted(p for p in _tracked(repo, untracked, "*.py") if _TEST.search(p) and tcr.kind(p, tcr.MARVIN_RULES) != "code")`.
5. In `lib/tests/test_affected_tests.py`: add test 9 above (the `lib/test_widget.py` / `lib/tests/test_test_widget.py` fixture case).
6. Run `pytest --collect-only -q lib | rg 'lib/test_(slot|change_rule)\.py'`; only if it shows a hit, add the minimal `testpaths`/`python_files`-equivalent exclusion to `pytest.ini` in this same PR (per the ticket's closing note) — otherwise leave `pytest.ini` untouched.
7. Run the full `lib/` and `brain-map/scripts/` test suites and confirm green (acceptance criterion).
8. Re-run `git ls-files | rg '(^|/)test_[^/]*\.py$' | rg -v '/tests?/'` to confirm the only matches left outside a `tests/` dir are the two production modules, `brain-map/scripts/test_*.py`, and the `bench/tasks/**` fixtures — i.e. no other file needs the new pattern or got missed.