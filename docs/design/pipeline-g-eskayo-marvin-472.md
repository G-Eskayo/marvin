## North-star fit

**Reuses:** the existing `### 1. Audit the system` bullet list in `skills/architecture-review/SKILL.md:26-32` (the `Tokens`/`Speed`/`Reliability`/`Organization`/`Robustness`/`Maintenance burden` checklist). The ticket's own "What to build" asks for exactly one more line in that section — no new heading, file, or mechanism needed.

**Why simplest sufficient:** the gap is a missing fact in the reviewer's process (Read can't see symlinks → it can misidentify a symlinked command file as an independent duplicate and destroy the real skill with an Edit), not missing tooling. One sentence closes it. The ticket explicitly says "Nothing else in the repo."

**Tokens:** one-time, fixed cost of ~2 sentences added to a skill doc, in exchange for preventing a destructive Edit-through-symlink on a real `SKILL.md` (`caveman`, `research`, `safety-monitor`) during some future review pass.

**North star 4 (tool for tools):** direct fit — `architecture-review` is the tool that improves MARVIN; this hardens it so it can't break another skill by mistake.

**User capability:** removes a failure mode the owner would otherwise have to catch manually before approving a suggestion; the reviewer carries the check instead. No judgment is taken from the owner — suggestions still require his approval.

**CONTEXT.md / ADR check:** searched `docs/adr/` and `CONTEXT.md` for symlink or architecture-review conflicts; nothing recorded governs this, so no decision to reconcile. ADR 0016 (scope) is already reflected in the file's current "Whole system, expanded 2026-07-09" section and is untouched by this change.

**Prior attempt (PR #1344):** same ticket, same worktree-equivalent, already implemented once. It was sent back by the pipeline for a Python-test CI failure (`pytest_failed: 12`, identical to baseline — pre-existing/unrelated flake, "tests steady," not caused by this docs-only change), so there's no content-based denial to correct. However its own (non-blocking) code review flagged real wording problems worth fixing this time:
1. The design doc quoted exact text that diverged from what was actually written into `SKILL.md`.
2. The companion tasks doc overclaimed a phrase would be "literally present" — an overspecified, brittle verification step — when the actual wording differed.
3. The rule stated "never Edit-in-place" without saying *why* — the hazard (silently overwriting the real skill file the link points to) was left implicit.

This attempt's task list and final sentence correct all three: no "literally present" claim, design-doc quote matches the real added line, and the line itself states the hazard.

## Tests

Ticket's "How we'll try to break it" section: **"Docs-only: exempt."** Confirmed accurate — the change is a single sentence added to a Markdown skill doc, no executable code, script, schema, input surface, dependency, or concurrency path is touched. No misuse-case list applies (nothing outward-facing, nothing parses untrusted input). No test files will be added or changed.

## Decisions

None — the ticket is fully specified (exact file, exact two-part rule content, exact insertion point). Nothing requires the owner to choose.

## Task List

1. Edit `skills/architecture-review/SKILL.md`: append one new bullet to the end of the `### 1. Audit the system` list (after the "Maintenance burden" bullet, currently ending at line 32, before the blank line and `### 2. Generate suggestions` heading). New bullet text:
   `- **Symlink safety**: Read cannot detect symlinks. Before calling a `commands/` file a duplicate of its SKILL.md, check `ls -l`; a symlink is not a duplicate — editing it through Edit would silently overwrite the real SKILL.md it points to. If a link genuinely must be replaced, `rm` it and write a new file, never Edit-in-place.`
   This satisfies both acceptance criteria: the rule lives in the review process section, and both halves are present — detection (`ls -l`) and replacement (`rm` + new file, never Edit-in-place) — plus the review-note fix of stating *why* (silent overwrite of the real file).
2. Diff-review the change: confirm it is a single added line with no other line in the file touched, and that the sentence reads correctly in context (flows after "Maintenance burden", before "### 2. Generate suggestions").
3. No test changes (docs-only, confirmed exempt above). No other files touched.