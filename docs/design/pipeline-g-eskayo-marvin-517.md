## North-star fit

**Reuses:** the existing `### Update CONTEXT.md inline` paragraph inside `skills/grill-with-docs/SKILL.md`'s `<supporting-info>` block (lines 72–76) — the new text is an addition to that same paragraph group, not a new section or mechanism. It also reuses `lexicon/SKILL.md`'s own stated trigger ("Term used 2+ times with stable meaning → worth formalising", line 14) verbatim as the criterion for "goes to lexicon too," rather than inventing a new reusability test. No new file, no new skill, no new frontmatter field — `calls: [grill-me, lexicon]` already exists on line 5; this just makes the body match what it already declares.

**Simplest sufficient approach:** a single short paragraph appended after the existing "Update CONTEXT.md inline" text, stating the CONTEXT.md-vs-lexicon split and naming the lexicon skill. No code, no changes to `lexicon/SKILL.md` or `CONTEXT-FORMAT.md`, no new cross-reference infrastructure.

**Tokens:** spends a few dozen tokens once in a skill file that's loaded during grilling sessions; this is a documentation fix closing a declared-but-dead dependency (`calls: lexicon` was already paid for, just unused) — no new ongoing cost. Saves tokens downstream per north star 4 ("tool for tools," compounding leverage): a term sharpened once during grilling becomes reusable across every future project's sessions via `lexicon.md`, instead of being re-derived from scratch in each project's own CONTEXT.md.

**More capable, not more passive:** yes — it makes an already-intended behavior (routing reusable terms to the shared lexicon) actually happen automatically during grilling, rather than requiring a human to separately notice and run the `lexicon` skill by hand later.

The ticket's own stated north star (4, tool for tools) checks out against the code — `calls: [grill-me, lexicon]` is real and unused, exactly as described; no correction needed.

**Decisions:** none. The original ticket text framed "wire it in vs. remove from `calls:`" as an open choice, but the current "What to build" section has already resolved it ("add a short paragraph... Keep `calls: [grill-me, lexicon]`"). No owner decision remains open.

## Tests (ticket is docs-only; "How we'll try to break it" is marked exempt)

This is a static-text addition to a markdown skill file — no code path, no input, no dependency, no concurrency, no permissions surface exists for it. The ticket's break-it section correctly marks itself exempt. The verifiable checks are the three acceptance criteria themselves, run as the "test suite" for this change:

1. `rg -n lexicon skills/grill-with-docs/SKILL.md` — must match line 5 (frontmatter) and at least one new body line.
2. Manual read of the new paragraph — must name both `CONTEXT.md` and the `lexicon` skill, and state which terms go where (project-specific → CONTEXT.md; reusable 2+-use stable-meaning terms → lexicon, per `lexicon/SKILL.md`'s own trigger).
3. `git diff` (or equivalent) on `skills/grill-with-docs/SKILL.md` — must show only the one paragraph added under "Update CONTEXT.md inline"; every other line (frontmatter, other `<supporting-info>` subsections, `<what-to-do>`) unchanged.

Misuse cases considered and ruled out as inapplicable for a pure-prose doc addition: bad/empty/huge/malformed input (no input accepted), dependency failure (no dependency called), repeats/concurrency (static file, no runtime), wrong permissions (file edit only, standard git flow), stale state (no state read), person's mistakes (covered by criterion 3 — scoping the edit to one paragraph prevents an editor from drifting into other sections).

## Task List

1. Edit `skills/grill-with-docs/SKILL.md`: under `### Update CONTEXT.md inline` (currently lines 72–76), append one paragraph after the existing two sentences, before the `### Offer ADRs sparingly` heading. Content: state that `CONTEXT.md` holds only project-specific meaning, and that a term meeting lexicon's own reuse trigger (used 2+ times with a stable meaning, per `lexicon/SKILL.md`) is also added to the shared lexicon via the `lexicon` skill — the two are not exclusive; a term can get both a CONTEXT.md entry and a lexicon.md entry.
2. Leave `calls: [grill-me, lexicon]` (line 5) and every other section of the file untouched.
3. Run `rg -n lexicon skills/grill-with-docs/SKILL.md` to confirm acceptance criterion 1.
4. Run `git diff` on the file to confirm only the one paragraph changed (acceptance criterion 3).
5. Re-read the new paragraph to confirm it explicitly names CONTEXT.md and the lexicon skill and says which terms go where (acceptance criterion 2).