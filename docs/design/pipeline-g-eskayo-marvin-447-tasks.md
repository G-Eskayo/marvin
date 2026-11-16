## Task List

1. In `lib/code_review_gate.py`: extract the rubric string out of `build_prompt()` into a module-level constant `RUBRIC` (same convention as `MAX_DIFF_CHARS`), and rewrite its text to add, after the existing "Do NOT report cosmetic changes." line and before "Respond with exactly one line...":
   - A `Resources:` paragraph naming: time complexity (O(n)-or-worse work added to a hot or per-request path where O(1) or an indexed/cached read already exists), space growth (a file/cache/log/worktree that grows unbounded, or anything a run creates and never cleans up when it ends — with an inline gloss of ADR 0065: "a disposable resource, one quick to recreate, is cleaned up as part of finishing the work, with no approval needed; leaving it behind is a bug"), and wasted calls (repeated network, token, or subprocess calls inside a loop that could be batched or cached). End it with the explicit boundary sentence: "A small, bounded, one-off loop is a micro-optimisation (note), not a resources regression (must-fix)."
   - Update the `[must-fix]` bullet's parenthetical to add "a resources regression as above" to its list of real defects.
   - Rename the `[note]` bullet's "performance" to "micro-optimisations".
   `build_prompt()` becomes `return f"{RUBRIC}\n\nDIFF:\n\n{diff}"` after the existing truncation step (unchanged otherwise).

2. Edit `docs/north-stars.md:31`: "where it saves tokens (or why it spends them)" → "where it saves resources (or why it spends them)".

3. In `lib/tests/test_code_review_gate.py`, add a small `_bullet(start, end)` slice helper (two-line function, anchored by `RUBRIC.index`, not fixed widths) plus the 6 tests listed under "Tests" in the design doc, appended after the existing test block (after line 336), with a short section comment naming marvin#447 and what they break.

4. In `lib/tests/test_north_stars.py`, add the 1 wording test listed under "Tests" in the design doc.

5. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_code_review_gate.py lib/tests/test_north_stars.py -v` and confirm all 7 new tests plus the full existing suite in both files pass.

6. Write the design doc and task list from this plan, verbatim and self-contained (no "see above" references that don't resolve inside their own file, no leaked scratch text).
