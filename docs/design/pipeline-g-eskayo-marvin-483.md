I have everything needed. Here's the plan.

## North-star fit

Reuses the existing `_render_chunk_paths()` helper in `skills/architecture-review/scripts/background_architecture_review.py:147` and its established directory-expansion/fallback pattern — this is a filter added inline to the existing `rglob` comprehension, not a new module or abstraction. No other file in the repo defines a skip-parts/skip-suffixes set to reuse (checked via grep); the closest precedent is `.gitignore` itself (`.gitignore:2-11`), which already excludes `__pycache__/`, `*.pyc`, `.pytest_cache/` — this change makes the reviewer's file list agree with what the repo already considers noise.

Simplest sufficient approach: two small module-level sets and a boolean guard inside the existing comprehension — matching the ticket's own "What to build" exactly (not its optional `git check-ignore --stdin` alternative, which would add a subprocess dependency and require the chunk to sit inside a repo for a low-value general case). North star 1 (fewer wasted tokens per unattended run): on the measured paper-dive chunk this cuts 16 of 36 listed paths, and it is pure, no-I/O-added computation, so the token savings are free (no added runtime cost, no new dependency). Leaves the user more capable indirectly: the unattended reviewer spends its fixed token/tool budget on real source instead of bytecode, so more of each chunk gets genuine review — no change to what a human does by hand.

One correction to the ticket: its "Original ticket text" appendix suggests filtering on `set(f.parts) & _SKIP_PARTS` (absolute path parts), but the refined "What to build" section correctly says to filter on `set(f.relative_to(expanded).parts) & _SKIP_PARTS` instead — using absolute parts would wrongly wipe out an entire chunk if the repo checkout itself sits under a path segment matching a skip name (e.g. a clone under `~/node_modules-backup/marvin` — edge case, but `relative_to(expanded)` is strictly safer and is what the acceptance criteria's "chunk that itself lives under a skipped name isn't wiped" line requires). I'll implement the relative-to version.

## Tests (written first)

All in `skills/architecture-review/scripts/tests/test_background_architecture_review.py`, alongside the existing `_render_chunk_paths` tests (lines 35–106), same fixture style (`tmp_path`, no mocking needed — this is pure filesystem + pure function, so no mock could hide real behavior):

1. **Acceptance criterion 1** — `a.py`, `__pycache__/a.cpython-311.pyc`, `.pytest_cache/v/cache/nodeids` in one dir → rendered output contains only `a.py`'s path, nothing from either cache dir.
2. **Acceptance criterion 2** — a dir holding only `__pycache__/x.pyc` and `.pytest_cache/README.md` → falls back to the bare directory bullet (reuses the existing empty-dir fallback path).
3. **Acceptance criterion 3** — run full existing test file; all current `_render_chunk_paths` tests (directory expansion, nested subdirs, file-passthrough, mixed, empty-dir fallback, nonexistent-dir fallback) must still pass unchanged.
4. **Whole-part match, not substring** — a file named `cache.py` at the top level is kept.
5. **Whole-part match, not substring** — a directory named `pycache_tools/` with a real file inside is kept (not treated as `__pycache__`).
6. **Top-level `.pyc`** — a `.pyc` file sitting directly in the chunk dir (no cache subdirectory) is dropped.
7. **Single-file chunk passthrough** — a chunk path given as a single file that itself has a `.pyc` suffix (or literally lives under a path segment named `__pycache__`) is rendered unchanged, since filtering only ever applies to the directory-expansion branch, matching the existing `test_file_path_is_rendered_as_is_not_expanded` contract.
8. **Each skip name individually** — one test covering `.mypy_cache`, `.ruff_cache`, `node_modules`, and `.git` (each as a one-entry case or table-driven), so every member of `_SKIP_PARTS` is pinned, not just the two named in the acceptance criteria.
9. **`.pyo` suffix** — also dropped, pinning both members of `_SKIP_SUFFIXES`, not just `.pyc`.
10. **Chunk dir itself under a skipped name isn't wiped** — chunk dir is `tmp_path/node_modules/my-skill/`, containing a real `a.py`; rendering it still returns `a.py` (because filtering checks parts *relative to* the expanded chunk dir, never parts above it).
11. **Empty input list** — `_render_chunk_paths([])` returns `""` (pins current edge-case behavior; "malformed input" class).

Not adding tests for: concurrency/repeats (pure function, no shared state, no I/O side effects), "each dependency failing" (only dependency is the local filesystem via `pathlib`, already covered by the existing nonexistent-directory fallback test, which this change doesn't touch), wrong permissions / unreadable subdirectory (pre-existing `rglob` behavior, unrelated to the filter logic this ticket adds — changing it would be unscoped), and stale state (function is stateless). These are genuinely N/A here, not skipped for convenience.

No Decisions needed — the ticket is fully specified and the one ambiguity (absolute vs. relative parts) is resolved by the acceptance criteria themselves.

## Task List

1. Add module-level `_SKIP_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".git"}` and `_SKIP_SUFFIXES = {".pyc", ".pyo"}` near the other module-level constants in `skills/architecture-review/scripts/background_architecture_review.py` (around line 65, after `CLAUDE_CALL_TIMEOUT`).
2. Write the 11 tests above in `skills/architecture-review/scripts/tests/test_background_architecture_review.py`, confirm they fail against current code (filter not yet applied).
3. Update `_render_chunk_paths()` (line 147) to filter the `rglob("*")` comprehension: keep a file only if `f.is_file()`, `not (set(f.relative_to(expanded).parts) & _SKIP_PARTS)`, and `f.suffix not in _SKIP_SUFFIXES`. Leave the empty-fallback (`if files: ... else append bare bullet`) and the non-directory passthrough branch untouched.
4. Run the full test file (`~/.agents/venv/bin/python -m pytest skills/architecture-review/scripts/tests/test_background_architecture_review.py -v`) and confirm all new and existing tests pass.
5. Run the full `lib`/skills pytest suite to confirm no regressions elsewhere (nothing else imports `_render_chunk_paths`, per grep, but verify broadly per repo convention).