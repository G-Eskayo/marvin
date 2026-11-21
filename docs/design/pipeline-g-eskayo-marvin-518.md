I have everything needed. Here's the plan.

## North-star fit

- **Reuses:** `lib/tests/test_rebuild_manifest.py`'s `TestCallsField` class (already on `main`, landed via #530 for the sibling ticket on `to-tasklist`/`calls: [to-issues]` — same shape of defect). Its two tests are the exact template for this ticket: `test_parse_frontmatter_on_real_X_has_no_calls_key` (direct `parse_frontmatter()` call on the real file) and `test_scan_skills_X_entry_has_no_calls_key` (`monkeypatch.setattr(rebuild_manifest, "SKILLS_DIR", skills_dir)` then `scan_skills()`, asserting the entry lacks `"calls"`). No new fixture style, no new harness — same class, two more methods for `improve-codebase-architecture`/`zoom-out`.
- **Simplest sufficient approach:** delete line 5 (`calls: [zoom-out]`) from `skills/improve-codebase-architecture/SKILL.md`, add the two tests following #530's exact pattern. Nothing else in the file changes — the body never referenced zoom-out, so there's no "wire it in" branch to design (the ticket already decided: stale, remove it).
- **Why not the previous attempt's shape (PR #1378):** that attempt invented its own ad hoc test style (brittle literal line-5 string check, `assert "zoom-out" not in entry.get("calls", [])` instead of `assert "calls" not in entry`, manual try/finally monkeypatching, shelling out to an external `grep` binary) and committed a stray `PR_DESCRIPTION.md` at repo root. All of that is now moot: #530 landed on `main` after that PR was opened and established the correct in-repo pattern (`monkeypatch.setattr`, asserting the key is absent, no subprocess grep). Following #530 directly avoids re-introducing any of the problems flagged in that review.
- **Tokens:** trivial — one line deleted, two small test methods appended to an existing class, no new files beyond the two docs/design scratch docs this pipeline already always writes.
- **Capability:** removes a phantom `calls:` dependency that would otherwise make the retrieval pipeline load the entirety of `zoom-out/SKILL.md` on every activation of `improve-codebase-architecture` for no reason — same waste class as #530 already fixed once; this closes the second flagged instance. Not user-facing, so "more capable vs. more passive" doesn't really apply — it's pure overhead removal.

No Decisions section needed: the ticket's "What to build" already resolves the only choice (remove, don't wire in), and the "Ticket 512 edits the body" rebase risk is moot since #512/#512-shaped commit hasn't landed on `main`.

## Tests (written first)

Ticket's "How we'll try to break it" is **Docs-only: exempt** (correct — no new runtime input-handling path, just a static frontmatter deletion exercised through the already-covered `scan_skills()`/`parse_frontmatter()` code path). Mirroring #530's `TestCallsField` class in `lib/tests/test_rebuild_manifest.py`:

1. `test_parse_frontmatter_on_real_improve_codebase_architecture_has_no_calls_key` — `parse_frontmatter()` on the real `skills/improve-codebase-architecture/SKILL.md`, assert `"calls" not in fm`. Pins AC1.
2. `test_scan_skills_improve_codebase_architecture_entry_has_no_calls_key` — `monkeypatch.setattr(rebuild_manifest, "SKILLS_DIR", skills_dir)` pointed at the repo's own `skills/`, run `scan_skills()`, find the `improve-codebase-architecture` entry, assert `"calls" not in entry`. Pins AC2.

Both fail today against current `main` (line 5 still present) and pass once it's deleted. No additional misuse surface applies — this is a one-line static deletion in a frontmatter file, not new code accepting external input, so bad/huge/malformed input, concurrency, permissions, and stale-state cases don't have anything to attach to beyond what the existing `TestParseModelScope`/`_hook_should_skip` tests already cover for this file.

## Task List

1. Add two new test methods to the existing `TestCallsField` class in `lib/tests/test_rebuild_manifest.py`, following #530's pattern exactly (`parse_frontmatter` direct check + `monkeypatch.setattr("SKILLS_DIR", ...)` + `scan_skills()` check), targeting `improve-codebase-architecture`/`zoom-out`. Run them and confirm both fail against current `main`.
2. Delete line 5 (`calls: [zoom-out]`) from `skills/improve-codebase-architecture/SKILL.md`'s frontmatter — no other line changes.
3. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_rebuild_manifest.py -v`, confirm the two new tests pass and all pre-existing tests (`TestParseModelScope`, the two `_hook_should_skip` tests, #530's `TestCallsField` tests) still pass with no regressions.
4. Confirm via `rg -n zoom-out skills/improve-codebase-architecture` that it returns nothing (direct sanity-check of AC3, matching what #530 did for its own sibling ticket).
5. Do not commit a `PR_DESCRIPTION.md` file at repo root — put the summary in the PR body instead (previous attempt's review flagged this). Note in the PR body, as #530's design doc did, that the real `~/.claude/manifest.json` regeneration is left to the existing live PostToolUse hook / next deploy rather than run manually from this worktree.