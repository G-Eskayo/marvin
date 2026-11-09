## North-star fit

**Reuses:** the budget-fitting mechanism already in `lib/session_start_report.py` (`fit()`, `_cap()`, the `_safe()` failure-isolation wrapper, and the temp-file+replace save in `_save_full_report`) — none of that changes. Reuses the existing `.gitignore` allow-list pattern in `~/.claude/.gitignore` (ADR 0022) for registering the one new file. Reuses ADR 0076's existing exclusion of `lexicon.md` from union-merge (already true, nothing to touch) — a normal edit/delete to that file gets a normal 3-way merge, not silently resurrected.

**Simplest sufficient approach:** the owner rejected the PR's "index now, definitions on demand" design (the Full-Memory shape) for this file specifically. The only thing that needs to change in `load_lexicon()` is *what it returns* (full text instead of a name list) — the surrounding cut/drop safety net in `fit()` already handles an oversized section generically, so it doesn't need new logic, just a smaller input. Shrinking the input is one content edit (move ~40 MCP-glossary bullets out of `lexicon.md` into one new sibling file), not a new subsystem.

**Where it spends/saves tokens:** spends slightly more per session than the merged PR's current state (full term text vs. names-only), but less than the pre-#1037 state, since the generic MCP glossary — 40 of 48 terms, most of it never referenced in a MARVIN session — no longer rides along at all. Net: the lexicon the model actually uses (Meta terms, `replacement cost`, `Workshop`, future domain terms) is now shown whole, every session, inside the existing 8,000-char budget; the dead weight is gone rather than compressed.

**Capability:** no behavior change for the user — this is report plumbing. It fixes a correctness defect (owner's chosen design wasn't what got built) rather than adding anything the user must learn or operate.

**Correction to the PR's own stated fit:** the PR claims it matches "the same shape 'Full Memory' already has" — the owner's decision explicitly rejects that shape for this file. The corrected fit is: full text is simpler to reason about and verify byte-for-byte than an index pointing at a file nobody is forced to open; it only works here because the input is kept small by moving the bulk of it elsewhere, not because an on-demand index is wrong in general.

## Decisions

None needed. The owner's decision comment (`lexicon` id, PR #1124) is unambiguous and has no note contradicting it, and re-reading the PR now shows no commits or comments since 2026-11-04T20:47:47Z — nothing has drifted. The one implementation detail left to me (the new file's name/path, `~/.claude/mcp-glossary.md`, flat like `lexicon.md` itself) is a non-product judgment call, not something requiring the owner's input.

## Tests first (`lib/tests/test_session_start_report_budget.py`)

Existing suite (15 tests) stays mostly intact — only the two that encode the rejected "names + pointer" design change. Written/edited before any implementation change, so each one fails against the current committed code and passes only once `load_lexicon()` is rewritten:

1. **Rewrite** `test_lexicon_lists_every_term_and_where_the_definitions_are` → `test_lexicon_shows_full_definitions_every_session`: assert the *definition text itself* appears (e.g. "observe pattern" from the `skill loop` entry), not just the term name — the inverse of today's assertion.
2. **Keep, resize** `test_real_script_output_fits_with_a_real_sized_home`: shrink the synthetic lexicon fixture to a size representative of the file *after* the MCP split (~10–15 small terms, not 60), so the test reflects the real post-fix shape instead of a size that can no longer fit full definitions.
3. `test_lexicon_with_no_terms_or_missing_adds_nothing` — unchanged, still valid (empty file, missing file).
4. **New:** `test_lexicon_truly_empty_file_adds_nothing` — a literal 0-byte `lexicon.md` (distinct from "has a heading but no terms").
5. `test_lexicon_that_is_not_text_does_not_break_the_report` — unchanged (malformed/binary content).
6. **New:** `test_lexicon_single_huge_line_with_no_newline_is_capped_safely` — one bullet whose definition is one giant line with no `\n`; verifies `_cap`'s `"\n" in head` fallback path doesn't raise and still respects `BUDGET` (misuse: someone pastes an unbroken block into the file).
7. **New:** `test_lexicon_unreadable_does_not_crash_the_report` — monkeypatch `Path.read_text` to raise `PermissionError`; assert the report still starts with `"MARVIN active"` (dependency/permission failure — exercises `_safe()` around `load_lexicon`).
8. `test_report_fits_the_cap_even_when_every_source_is_huge` — unchanged, kept as the stress case: even if the lexicon is accidentally re-bloated (a person pastes the MCP glossary back in by mistake — the actual misuse this ticket is defending against), total output still stays ≤ `BUDGET`.
9. **New:** `test_huge_lexicon_alone_is_cut_or_dropped_without_crashing` — isolates the huge-lexicon case (other sections small) to confirm the lexicon section specifically degrades via `fit()`'s cut-or-drop path, not a special case.
10. `test_banner_is_always_the_first_line`, `test_a_cut_section_says_so_and_where_the_rest_is`, `test_the_full_report_is_saved_whole_for_whatever_was_cut`, `test_sync_block_is_never_pushed_out_by_bulk_below_it`, `test_checklist_notes_survive_a_huge_morning_brief`, the three handoff tests, `test_same_state_gives_byte_identical_reports`, `test_unwritable_full_report_path_still_prints_the_report` — all unchanged; they don't touch `load_lexicon`'s output shape.

Not unit-testable (content/infra, not code) but verified by hand before/after the commit, matching ADR 0022's own verification method:
- `git check-ignore -v ~/.claude/mcp-glossary.md` → must report **not ignored** once `.gitignore` is updated (otherwise the new file silently never syncs to the other Mac — the exact silent-breakage north star 2 forbids).
- Run the real script against the live `~/.claude` and record the new live byte count, the way PR #1124 recorded "12,783 → 1,621."
- Re-run the related suites named in the PR: `test_session_start_sync_block.py`, `test_morning_brief.py`, `test_module_path_is_own_dir.py`, `test_marvin_hooks.py`, `test_code_sync_main_only.py` — confirm still green.

## Task List

1. Edit `~/.claude/lexicon.md`: remove the ~40-term "## MCP (Model Context Protocol)" block, replace it with a 2-line pointer to the new file; leave Meta, `replacement cost`, `Workshop` untouched.
2. Create `~/.claude/mcp-glossary.md` holding the removed MCP terms verbatim under their original heading.
3. Edit `~/.claude/.gitignore`: add `!/mcp-glossary.md` to the allow-list (ADR 0022) so the new file actually syncs; verify with `git check-ignore -v`.
4. Commit and push those three `~/.claude` changes through the existing self-hosted sync (no GitHub PR exists for this repo — commit directly, let the push hook/cron carry it to the other Mac).
5. On branch `ticket/1037-session-overhead`: rewrite `load_lexicon()` in `lib/session_start_report.py` to return the lexicon's full text (minus its H1/intro) under one `## Lexicon` heading, instead of names-only + pointer; update its docstring (drop the "Full Memory" shape framing the owner rejected).
6. Update `docs/session-start-checklist.md` row 3 ("Lexicon") to describe full definitions, not names-plus-pointer, and note the MCP glossary now lives in `~/.claude/mcp-glossary.md`, not loaded at session start.
7. Update `skills/lexicon/SKILL.md`'s "Adding an Entry"/"Sections" guidance: generic protocol/vendor glossaries go in `~/.claude/mcp-glossary.md`, not `lexicon.md`, so the bloat this ticket is fixing doesn't recur.
8. Apply the tests-first changes above to `lib/tests/test_session_start_report_budget.py` (items 1–9), run the full file plus the five related suites, confirm green.
9. Run the real script against live `~/.claude`, record the new live byte count.
10. Update PR #1124's description: tick the chosen Decision option (already done by the owner's comment), rewrite the "What changes"/"Live size" prose to match the actual full-definitions implementation, drop the now-inaccurate "Term names every session" framing.
11. Commit the `lib/`/`docs/` changes on `ticket/1037-session-overhead` and push.
12. Post a reply comment on PR #1124 carrying `<!-- marvin:decisions-addressed -->`: states the chosen option was carried out, names the commit, and notes no screenshots were retaken because nothing visual changed (this is a backend text-generation change).