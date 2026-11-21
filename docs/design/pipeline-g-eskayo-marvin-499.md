Nothing in CONTEXT.md blocks or constrains this. The ticket is small and fully specified, docs-only (exempt from "how we'll try to break it" per the ticket itself). Now I'll write the plan.

## North-star fit

**Reuses:** the skill-loading contract already documented in this repo's root `CLAUDE.md` ("load any referenced files… from the same directory") — this ticket doesn't add a new mechanism, it just makes `diagnose/SKILL.md` actually invoke that existing contract by naming `retrospective.md`. It also reuses the existing `I:`/`S:`/`F:` retrospective format and the existing writer: `skills/self-improve/SKILL.md` "Annotation format" (line 43) already appends dated entries to a skill's `retrospective.md`, confirmed by reading that file — so no second writer is needed, matching the ticket's own "Not added" note.

**Simplest sufficient approach:** a single sentence inserted into Phase 3, immediately before the "MARVIN-specific gotcha classes" list (`skills/diagnose/SKILL.md:80`). No new file, no new phase, no change to Phase 6 — the ticket text explicitly scopes out a Phase 6 writer addition (verified: `self-improve` already owns that), so adding one would duplicate logic. The ticket's own "Original ticket text" (filed 2026-09-14) proposed also editing Phase 6; the canonicalized "What to build" section supersedes that and deliberately drops it — I'm following the canonicalized version, not the appendix.

**Tokens:** spends a trivial, one-time edit (~1 sentence); saves tokens repeatedly going forward, since every future `diagnose` invocation that reaches Phase 3 will now pull in `retrospective.md`'s `S:` lines (dated, pre-distilled verification approaches) instead of either missing that knowledge entirely or an agent re-discovering it from scratch.

**North-star 4 (tool for tools):** this is exactly "lessons that compound instead of sitting unread" — a one-line fix that reconnects an already-maintained knowledge store to the loop that should consume it. No north star argues against it.

**Leaves the user more capable:** yes — this is infrastructure for the agent's own diagnosis quality, not user-facing automation; it doesn't remove any judgment call from a human.

## Tests

The ticket's "How we'll try to break it" section states: **"Docs-only: exempt."** This is correct — `skills/diagnose/SKILL.md` is a prose instruction file with no executable path, no input parsing, no external-facing surface, and no existing test suite covering its prose content. There is no code seam to attack (no bad/empty/huge input, no dependency to fail, no concurrency, no permissions boundary). I confirmed this by reading the file: it's pure markdown instructions, not a script or parser.

The one thing worth a manual check (not an automated test, since none exists for this file class): confirm the inserted sentence doesn't break the existing Markdown structure or the gotcha-class list's own formatting — i.e., diff the file before/after to ensure only the intended line is added.

No Decisions section is needed — the ticket is fully specified and the "no second writer" open question is already settled by reading `self-improve/SKILL.md`.

## Task List

1. Edit `skills/diagnose/SKILL.md` Phase 3: insert the sentence "Also skim `retrospective.md` (same folder) for past sessions' lessons, especially `S:` lines, which record verification approaches that worked." immediately before the "**MARVIN-specific gotcha classes**" paragraph (currently line 80), as its own paragraph.
2. Do not touch Phase 6 (no second writer — `self-improve/SKILL.md`'s Annotation format already owns writing retrospective entries).
3. Re-read the diff to confirm only that one paragraph was added and Markdown structure/formatting around it is intact.