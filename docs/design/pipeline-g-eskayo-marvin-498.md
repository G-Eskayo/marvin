I now have everything needed. Here's the plan.

## North-star fit

**Reuses:** the "bundle a long reference, link it with `See [X.md](X.md)`" pattern already used throughout `skills/` — `skills/tdd/SKILL.md:18` linking `tests.md`/`mocking.md`, `skills/self-improve/SKILL.md:29` linking `quality-filter.md`, `skills/improve-codebase-architecture/SKILL.md:70` linking `HTML-REPORT.md`, and `skills/research/SKILL.md:15` linking `epistemic-framework.md`. Each bundled file opens with a single `# Title` H1 before its moved `##` sections (confirmed in `quality-filter.md:1`, `tests.md:1`) — `REFERENCE.md` will follow that same shape rather than inventing a new one. `write-a-skill/SKILL.md` already names this exact pointer pattern as its own "Advanced features" template line 60 (`[Link to separate files: See [REFERENCE.md](REFERENCE.md)]`) — so the fix is literally applying the skill's own documented template to itself.

**Simplicity:** a pure cut-and-paste plus a 2-line pointer; no new mechanism, no script, no change to `lib/skill_index.py` (which only reads each skill's frontmatter `description`, confirmed in `docs/skills.md:3`, so moving body content doesn't touch the generated skills index).

**Tokens:** spends a few minutes of edit time once; saves tokens on every future load of this skill (shorter file read into context) and removes the self-contradiction that an architecture-review pass would otherwise re-flag (compounding leverage).

**North star 4 (tool for tools):** direct fit — this is the skill that teaches other skills how to be well-formed; it should model its own rule rather than exempt itself.

**User impact:** docs-only, no behavior change for Gil; doesn't make him more passive or more capable either way — pure hygiene.

**Ticket's stated fit (North star 4) checked against the code:** correct as stated; no correction needed.

---

## Files already read in full
- `skills/write-a-skill/SKILL.md` (130 lines / `wc -l` 129) — confirmed current violation and exact line boundaries.
- `docs/agents/decisions-format.md`, `docs/north-stars.md`, `docs/skills.md` — confirmed conventions and that no decision is needed.
- Confirmed no `skills/write-a-skill/REFERENCE.md` exists yet (`Glob` empty).
- Confirmed the `See [X.md](X.md)` + standalone-H1-bundled-file pattern via `tdd/tests.md`, `self-improve/quality-filter.md`.

## Exact edit boundaries (verified by line number)
- Move lines 38–97 of current `SKILL.md` (the `## SKILL.md Template` heading through the end of the "bad example" paragraph in `## Description Requirements`, inclusive of the blank line 68 between them) into `REFERENCE.md`, prefixed with a new `# write-a-skill Reference` H1.
- Replace those lines 38–97 in `SKILL.md` with one short section carrying the ticket's exact required wording.
- Leave `## When to Add Scripts` (99), `## When to Split Files` (109), `## Review Checklist` (117) untouched, i.e. everything from line 98 (now line ~40ish after the cut) onward is otherwise unchanged.
- Net effect: ~130 lines → ~75 lines, well under the 100-line ceiling.

## Decisions
None — nothing in this ticket requires an owner choice; the ticket fully specifies the target content and wording, and no prior denial/failure comments exist on #498.

## Tests
"How we'll try to break it" states **"Docs-only: exempt"** — a recognized, enforced category (`lib/tests/test_commit_check.py`, `lib/tests/test_build_type_measure.py` both test for `docs-only` handling), so no new automated test is required. In place of code tests, the verifiable checks that stand in for them here (each directly maps to an acceptance criterion, and each is itself a "test that tries to break it" against markdown-link and line-count misuse):

1. `wc -l skills/write-a-skill/SKILL.md` reports a value under 100 (bad/boundary input: must check the *actual* rendered line count after the edit, not an estimate — this is exactly the mistake the ticket's own "Original ticket text" flagged as unverified in the prior attempt that left it at ~117).
2. Diff `REFERENCE.md`'s moved sections against the original file's git history (`git show HEAD:skills/write-a-skill/SKILL.md`) to confirm the template block and the Description Requirements section (including both the good and bad example code blocks) are byte-for-byte unchanged — catches accidental reflow/retyping corruption.
3. Grep `SKILL.md` for the literal substring `REFERENCE.md` to confirm the link is present and uses the established relative-path, same-directory form (not an absolute or `~/.agents`-prefixed path, which would break once synced elsewhere per ADR 0022).
4. Grep `SKILL.md` for `1024` and for `Use when` to confirm the inline rule text acceptance criterion literally survived the edit (not paraphrased away).
5. Confirm `REFERENCE.md` is actually reachable one level deep from `SKILL.md` (Review Checklist line 127's own "References one level deep" rule) — i.e. no further nested pointer.
6. Confirm `## When to Add Scripts`, `## When to Split Files`, and `## Review Checklist` sections are present, unmodified, and still in order after the edit (misuse case: an edit tool accidentally reordering or truncating trailing sections).
7. Re-render/lint the new `REFERENCE.md`'s frontmatter-fields bullet list and the two fenced code blocks (the `md` template fence and the two example fences) to confirm fence delimiters are balanced and didn't get merged or truncated by the line-range cut (malformed-input case: an off-by-one line slice is the single most likely failure mode of this exact edit).

## Task List

1. Create `skills/write-a-skill/REFERENCE.md` with a `# write-a-skill Reference` H1, followed by the verbatim `## SKILL.md Template` section (code block + Frontmatter fields list) and the verbatim `## Description Requirements` section (including both good and bad examples), copied exactly from current `SKILL.md` lines 38–97.
2. Edit `skills/write-a-skill/SKILL.md`: delete lines 38–97 and replace with a short section containing exactly: "Template, frontmatter fields and description rules: see [REFERENCE.md](REFERENCE.md). The description is the only thing the agent sees when choosing a skill: say what it does, then 'Use when ...' triggers, max 1024 chars." under an appropriate short heading.
3. Verify `## When to Add Scripts`, `## When to Split Files`, and `## Review Checklist` are unchanged and immediately follow the new short section.
4. Run `wc -l skills/write-a-skill/SKILL.md` and confirm it reports under 100; run the verification checks listed under Tests (steps 2–7 above) by inspection/grep.
5. Run `git diff` to review the full change before handing off, confirming no unrelated whitespace or formatting drift.