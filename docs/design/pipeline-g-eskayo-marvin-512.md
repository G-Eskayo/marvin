## North-star fit

**Reuses:** the replacement text is already fully specified in the ticket ("What to build"), and the pattern it follows is the existing cross-reference style already used three times in this same file — `SKILL.md` lines 25, 66, and 70 already say "see `[LANGUAGE.md](LANGUAGE.md)` for the full list" / "for the full HTML scaffold" instead of inlining content. This ticket just extends that same single-source-of-truth pattern to the one place (lines 12-29) that still inlines a copy. No new file, script, or abstraction is introduced.

**Simplicity:** this is the simplest sufficient change — delete a drifting duplicate, add a two-line pointer. There's no alternative design to weigh; the ticket's proposed replacement text is correct and complete (verified below).

**Tokens:** saves ~300 tokens/run (per the ticket's estimate) by loading the glossary once (from `LANGUAGE.md`, which the skill already loads via existing links) instead of twice. Fits north star 1 directly.

**Phone-OS / north star 5:** not applicable — this is a docs-token change, not infra/compute placement. Runs wherever the ticket pipeline executes (this worktree, no machine-specific work).

**User capability:** neutral-to-positive. It removes a maintenance trap (two copies that can silently drift — confirmed below: two LANGUAGE.md principles already have no short form in SKILL.md) without changing what the skill tells the agent to do. No human is doing less; this only removes redundant agent-loaded text.

**Verification of the ticket's claims (read before planning):**
- `skills/improve-codebase-architecture/SKILL.md` lines 12-29 hold the `## Glossary` (8 terms) and a 3-item "Key principles" list, all shortened restatements of `LANGUAGE.md`'s "Core terms" and "Principles" sections.
- `LANGUAGE.md` defines all 8 glossary terms (Module, Interface, Implementation, Depth, Seam, Adapter, Leverage, Locality) and 5 principles (deletion test, interface-is-test-surface, one-vs-two-adapters, plus two with no SKILL.md short form: "Shallow modules accumulate at boundaries under time pressure" and "Depth is not size") — confirming the ticket's drift claim.
- `skills/self-improve/scripts/rebuild-manifest.py`'s `parse_frontmatter()` only reads text between the opening `---` and the first `\n---` (the YAML frontmatter block) — it never parses `SKILL.md` body content, so removing the Glossary/Key-principles prose cannot affect the manifest. Confirmed by reading `scan_skills()` (lines 170-208): it only uses `fm.get("tags"/"name"/"calls"/"model-scope")`.
- No other file in the repo links to a `SKILL.md#glossary` or `#key-principles` anchor (grepped repo-wide) — safe to remove with no dangling references.
- Current word count: `wc -w skills/improve-codebase-architecture/SKILL.md` → **930 words** today (ticket says 958; will record the actual measured number, before and after, in the PR rather than the ticket's estimate).

No ADR or `CONTEXT.md` entry governs this file's structure, so nothing to reconcile.

## Tests

"How we'll try to break it" says **"Docs-only: exempt."** This is a pure prose edit to a Markdown skill file with no code path, no executable logic, and no input surface — nothing outward-facing or executable to attack. No misuse scenarios (bad/empty/huge input, dependency failure, concurrency, permissions, stale state) apply to a static doc edit, so no tests are written for this change. Verification is the three mechanical checks already done above (frontmatter-only manifest parser, no dangling anchors, LANGUAGE.md already covers every removed term) plus a word-count check after the edit, reported in the PR per the acceptance criteria.

## Decisions

None. The ticket is fully specified: exact replacement text given, exact lines identified, exact acceptance criteria. Nothing requires an owner choice.

## Task List

1. In `skills/improve-codebase-architecture/SKILL.md`, replace lines 12-29 (the `## Glossary` section through the "Key principles" list, up to but not including the "This skill is _informed_ by..." line) with the ticket's exact two-line `## Vocabulary` block pointing to `LANGUAGE.md`.
2. Leave the "This skill is _informed_ by the project's domain model..." line immediately after it unchanged.
3. Leave `LANGUAGE.md` itself untouched (acceptance criterion: "LANGUAGE.md is unchanged").
4. Re-run `wc -w skills/improve-codebase-architecture/SKILL.md` to get the new word count; confirm the drop is ≥200 words (acceptance criterion).
5. Spot-check `skills/self-improve/scripts/rebuild-manifest.py` behavior is unaffected (already confirmed via code reading above — no manifest rebuild needed, just note this confirmation in the PR body as the ticket requests).
6. Write the PR description recording the before/after word count and the frontmatter-only confirmation, per the ticket's "What to build" instruction.