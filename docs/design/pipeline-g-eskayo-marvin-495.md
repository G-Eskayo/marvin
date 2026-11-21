## North-star fit

- **Reuses:** `tests/test_skill_doc_links.py` (file + test pattern) — a pytest test that reads a `SKILL.md` file's text and asserts literal content invariants (presence/absence of specific strings/links). This ticket is the same shape of problem (a skill doc's prose must match reality), so I'll add a sibling test file rather than inventing a new verification mechanism.
- **Simplest sufficient approach:** direct text edits to `skills/index/SKILL.md` plus one small content-assertion test. No new tooling, no change to `rebuild-manifest.py`/`retrieve.py`/the manifest schema — the ticket explicitly carves that out as "a separate idea, not part of this."
- **Tokens:** net saver — deletes a ~14-line stale `## Examples` block (~200 tokens loaded every time an agent reads this skill) and replaces a non-existent/misleading coverage claim with one accurate sentence. Spend is a few lines of edit plus one short test file.
- **Phone-OS direction:** neutral — pure documentation accuracy, not plumbing.
- **More capable, not more passive:** yes — an agent on the manual fallback path currently has no signal that most memory files aren't in the manifest, so it silently under-searches. Telling it to also scan `MEMORY.md` makes its retrieval behavior match reality instead of a false sense of completeness.

**Correction to the ticket's own "What to build":** the ticket's literal instruction ("Line ~40: replace 'is the unified index for all skills AND knowledge files' with...") no longer matches the file. I checked: that sentence does not exist anywhere in the current `skills/index/SKILL.md` (confirmed by grep — zero matches for "unified" or "AND knowledge files"). The file was restructured by PR #476 (`b28ff33d`, already merged on `main`), which rewrote the "Fallback" section into the current three-outcome format (ranked results / `No relevant files found.` / `Failed to run`) — the ticket's own text calls this out as a companion PR that "rewrites the fallback trigger" while this ticket "fixes what the fallback claims to cover." So acceptance criterion 1's "unified index" clause is **already satisfied** (nothing to delete there); what's still missing is a correct, affirmative coverage statement that sends the agent to `MEMORY.md` on the manual path — criterion 2 is not yet met. I'll add that sentence into step 2 of the existing manual-fallback numbered list (the literal "manual path" in the current file), which is the structurally correct home for it now that the old intro sentence is gone. This is a direct, non-ambiguous resolution consistent with the ticket's intent and acceptance criteria, not a design choice — no Decisions section needed.

Current file (98 lines) — exact regions to touch:
- Lines 28–47 (`## Fallback: manual manifest matching`, specifically step 2 of the numbered list at line 42): add the corrected coverage sentence.
- Lines 58–72 (`## Examples` heading through its three examples, up to but not including `## Manifest Structure`): delete entirely — removes all three stale/wrong examples, including both `reference_mcp.md` mentions (lines 63, 71) and the nonexistent "build" skill / "tdd... calls: [diagnose]" claims.
- Line 89 (`## Keeping the Manifest Current`, item under "When creating a new skill or memory file:"): reword to "When creating a new skill (or a knowledge file you want found by tag):" per the ticket's "What to build" wording (the operative spec; the ticket's own appended "Original ticket text" uses slightly different wording — "retrievable by tag" — but "What to build" is the current, intended spec and I'll follow it).

No other files need changes. `manifest.json` itself lives outside this repo (`~/.claude/manifest.json`, a generated runtime artifact) and is explicitly out of scope.

## Decisions

None. The ticket resolves its only open question itself ("Whether `rebuild-manifest.py` should index memories automatically is a separate idea, not part of this"), and the line-number correction above is a direct textual fix, not a design choice.

## Tests (written first)

The ticket's "How we'll try to break it" section states "Docs-only: exempt" — correct: this is a static prose file with no parser, no inputs, no dependencies, no concurrency surface, and it isn't outward-facing, so the misuse categories (bad/huge/malformed input, dependency failure, repeats/concurrency, wrong permissions, stale state, person's mistakes) don't have a meaningful target here — there's no code path to feed any of those into. I checked for one anyway: the only other file referencing `reference_mcp`-style naming is `skills/self-improve/scripts/tag-files.py`'s unrelated `MEMORY_TAGS` dict key (used for live manifest tagging, not for this doc), so there's no code that parses this file's prose and could break from the edit.

Reusing the `tests/test_skill_doc_links.py` pattern, I'll add one small regression test, `tests/test_index_skill_doc.py`, asserting the acceptance criteria as literal content checks so verify fails if the doc regresses:

1. `test_no_stale_examples_heading` — `## Examples` does not appear in `skills/index/SKILL.md`.
2. `test_no_unified_index_claim` — the string `"unified index for all skills AND knowledge files"` does not appear.
3. `test_no_reference_mcp_dot_md` — the string `reference_mcp.md` does not appear anywhere in the file.
4. `test_manual_path_mentions_memory_md` — the fallback/manual-path text contains a reference to scanning `MEMORY.md` (confirms criterion 2 is actually met, not just the negative checks).

## Task List

1. Edit `skills/index/SKILL.md` step 2 of the "Failed to run" numbered list (around current line 42) to state what the manifest actually indexes (every skill plus only knowledge files carrying `tags:` frontmatter — 2 today) and instruct scanning `MEMORY.md`'s one-line hooks on this manual path.
2. Delete the `## Examples` section (current lines 58–72, i.e. the heading through its three example blocks, stopping right before `## Manifest Structure`).
3. Edit `## Keeping the Manifest Current` (current line 89) to change "When creating a new skill or memory file:" to "When creating a new skill (or a knowledge file you want found by tag):".
4. Add `tests/test_index_skill_doc.py` with the four assertions above.
5. Run the new test file (and the existing `tests/test_skill_doc_links.py` for the sibling pattern) to confirm both pass.