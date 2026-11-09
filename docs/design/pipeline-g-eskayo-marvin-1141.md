## North-star fit

Reuses `load_lexicon()`'s pre-#1037 shape (`git show ticket/1037-session-overhead:lib/session_start_report.py`, before PR #1124's edit: `return f"## Lexicon\n\n{f.read_text()}"`) and the already-existing `reference-mcp` memory note (`/Users/gileskayo/.claude/projects/-Users-gileskayo/memory/reference-mcp.md`, 400 lines, superset of every MCP term currently in the lexicon's MCP section) as the "knowledge file" the owner's decision asks to move the glossary into — no new file. `MEMORY.md` already indexes it (`[MCP reference](reference-mcp.md)`), so the index-once/read-on-demand half of the pattern (north star: Full Memory, CONTEXT.md:1763) is already in place; nothing new to wire.

Simplest sufficient approach: delete the MCP section from `~/.claude/lexicon.md` (live config, outside this git repo) and revert `load_lexicon()`'s body from "names only" back to full text, keeping the robustness checks (missing/empty/binary-safe) PR #1124 added, which the owner's decision didn't ask to undo. The existing `fit()`/`_cap()` budget machinery (unmodified) already degrades any oversized section gracefully, so no new truncation logic is needed inside `load_lexicon()` itself.

Token cost: spends a small one-time edit; saves ongoing confusion from a lexicon that showed names without definitions (the thing #1037 was trying to fix in the first place, just overshooting on one term). Leaves Gil more capable: the lexicon is usable again without an extra file hop for non-MCP terms, and the MCP glossary isn't duplicated or lost — it lives once, in its fuller form, where it already was.

## Tests to write first

In `lib/tests/test_session_start_report_budget.py`:

1. **Rewrite** `test_lexicon_lists_every_term_and_where_the_definitions_are` → full definitions shown, not just names: assert `"observe pattern"` (part of the "skill loop" definition) **is** present; drop the `"lexicon.md" in out` assertion (no path pointer in the reverted format, matching the pre-#1037 shape). Rename to `test_lexicon_shows_full_definitions`.
2. **Keep unchanged** `test_lexicon_with_no_terms_or_missing_adds_nothing` and `test_lexicon_that_is_not_text_does_not_break_the_report` — these are the PR's genuine robustness additions (empty/missing/binary lexicon), not touched by the owner's decision; verify both still pass against the new body.
3. **Keep unchanged** `test_report_fits_the_cap_even_when_every_source_is_huge` (2,000 synthetic terms, 300 chars each) — now exercises the full-text code path instead of name-joining; must still assert `len(out) <= ssr.BUDGET`, proving `fit()`'s truncation still protects the hook cap even though `load_lexicon()` no longer self-limits.
4. **New** — malformed markdown: a lexicon with a bullet missing its closing `**` (e.g. `"- **broken term — no closer\n"`) plus one well-formed bullet. Assert the report doesn't raise and the well-formed term's definition still appears (a person's mistake while hand-editing shouldn't blank the section).
5. **New** — wrong permissions: `lexicon.md` with mode `0o000` (skip on a platform where root/the test runner ignores permissions — guard with `os.access`). Assert `_safe(load_lexicon)` swallows the `PermissionError` (as `main()` already wraps the call) and the rest of the report still prints, starting with `"MARVIN active"`.
6. **New** — real-sized run: extend `test_real_script_output_fits_with_a_real_sized_home` (or add a sibling) using a lexicon fixture shaped like the *post-split* live file (Meta's 3 terms + 2 trailing terms, no MCP section) and assert the full definition text for at least one term (e.g. `"symlink skill into"`) appears verbatim in stdout — proving the real hook run, not just the mocked fixture, shows full text now that the file is small.

Not written: a concurrency test for lexicon.md being edited mid-read. The script is a single-shot process invoked once per session start; `Path.read_text()` on a file being swapped via temp-file-replace (the pattern CLAUDE.md's own "Edit lexicon mid-session" already uses) is not a realistic race worth a flaky test — the existing `_safe()` wrapper already turns any read failure into "section omitted," which is the correct behavior.

## Decisions

None needed. The owner already decided the only open question on PR #1124 ("lexicon" — full definitions, MCP glossary moved out). No other ambiguity in this ticket requires a fresh choice; where I had to pick between two low-risk options (leave a backlink pointer in `lexicon.md` after deleting the MCP section, vs. a clean deletion), I'm choosing the clean deletion since `MEMORY.md` already indexes `reference-mcp.md` every session — a pointer would just duplicate that.

## Task List

1. Write/update the tests listed above in `lib/tests/test_session_start_report_budget.py` (red first — confirm they fail or are mismatched against the current "names only" behavior).
2. On branch `ticket/1037-session-overhead`: re-pull/inspect its current head (`98bc265b`) immediately before editing, to confirm the PR hasn't moved since the decision was recorded (ticket's own break-it case).
3. Edit `lib/session_start_report.py`'s `load_lexicon()`: keep the existence/terms-detection/binary-safety guard, change the return value from the comma-joined term-name list back to the full file text (`f"## Lexicon\n\n{text}"`), update its docstring to explain why (marvin#1141 decision, MCP glossary now lives in `reference-mcp`).
4. Run the full test file plus the related suites named in the PR body (`test_session_start_sync_block.py`, `test_morning_brief.py`, `test_module_path_is_own_dir.py`, `test_marvin_hooks.py`, `test_code_sync_main_only.py`) to confirm no regressions.
5. Update `docs/session-start-checklist.md` row 3 ("Lexicon") to describe the reverted behavior (full definitions every session; MCP protocol glossary lives in the `reference-mcp` memory, not duplicated here).
6. Commit on `ticket/1037-session-overhead` and push.
7. Directly edit the live `~/.claude/lexicon.md` (outside the git repo, same convention as CLAUDE.md's "Add new terms mid-session via `Edit ~/.claude/lexicon.md`"): delete the `## MCP (Model Context Protocol)` section (lines 14–63, the two flanking `---` dividers plus all MCP bullets), leaving `## Meta` and the two trailing terms (`replacement cost`, `Workshop`) intact. No edit needed to `reference-mcp.md` — it already covers every term being removed.
8. Run `~/.agents/venv/bin/python ~/.agents/lib/session_start_report.py` under a real session once to sanity-check the live output shows full lexicon definitions and still starts with the identity banner and fits under budget.
9. Post a reply comment on PR #1124 via `gh pr comment 1124 --body-file -`, carrying `<!-- marvin:decisions-addressed -->`, stating: the commit SHA that reverted `load_lexicon()`, that the live `~/.claude/lexicon.md` was edited directly (not part of this diff) to drop the MCP section into the pre-existing `reference-mcp` memory note, and that no screenshots were retaken because this is a backend text-output change with no UI.
10. Confirm ticket #1141 auto-closes once PR #1124 is addressed (per its own filing rule); no manual close needed.