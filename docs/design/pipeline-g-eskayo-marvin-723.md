## North-star fit

**Reuses:** the decision text already drafted in the issue body itself (the promoted "What to build" section gives near-final prose for all three edits), plus the existing break-it bar from ADR 0063 (`docs/adr/0063-tests-try-to-break-it-enforced-at-every-gate.md`) and the headless/record pattern already established for Decisions sections (`docs/agents/decisions-format.md`). No new file, machinery, or abstraction — this is a three-spot text edit to `skills/to-prd/SKILL.md`.

**Simplicity check:** the triage pass already settled the one design fork in the original ticket (link `docs/agents/decisions-format.md` vs. inline it) by verifying `decisions-format.md` doesn't exist in the other repos `to-prd` runs in (clarity-captions, marvin-voice, finance-os, marvin-mobile, portfolio-website-updater). I re-confirmed `skills/to-prd/SKILL.md` currently names that file nowhere at all — so the fix is purely additive-and-correcting prose, not an inline-vs-link migration. Nothing simpler than editing the three spots the ticket names is available.

**Tokens:** this removes one blocking round-trip (the "which modules get tests" question) from every PRD run, which matters most in headless runs where the question would otherwise stall the pipeline indefinitely. Spend here is one small doc edit; saved is a stalled run per headless PRD.

**Phone-OS direction:** N/A (doc-only instruction fix, no runtime behavior).

**More capable, not more passive:** yes — the owner is no longer asked a question with a fixed, policy-determined answer ("test everything," ADR 0063), and a PRD can no longer quietly plan away tests the merge gate will later reject; that gap surfaces at spec time instead of failing downstream at every child ticket's gate.

No north star argues against this work.

## Decisions

None. The one real fork in the original ticket text (link vs. inline the decision format) was already resolved during triage and is stated as settled fact in the issue's "What to build" section, not left open. Nothing else in the acceptance criteria requires an owner choice.

## Files read

- `skills/to-prd/SKILL.md` (current state — lines 8, 20, 64–70 are the three edit sites)
- `docs/agents/decisions-format.md` (the format being inlined, not linked)
- `docs/adr/0063-tests-try-to-break-it-enforced-at-every-gate.md` (the break-it bar cited in the new Testing Decisions bullet)
- `skills/to-issues/SKILL.md`, `skills/triage/SKILL.md` (checked for the existing decisions-format.md link pattern — confirmed those two *do* link it; out of scope here, ticket only targets `to-prd`)
- `CONTEXT.md` (searched for conflicting decisions on `to-prd`/decisions format — none found)

## Tests (written first)

The ticket's "How we'll try to break it" section states: **"Docs-only: exempt."** This is a prose/instruction edit to a skill file with no executable code path and no test suite that covers `SKILL.md` body content (`lib/skill_index.py` only reads frontmatter — name/description/tags — which is untouched). This matches ADR 0063's stated consequence: *"Docs- or config-only changes pass the commit check with a stated reason."*

So: no automated tests to write. In place of tests, verification is a direct re-read of the edited file against each acceptance criterion, plus one explicit misuse case the ticket's exemption doesn't cover:

1. **Misuse case not covered by the exemption — stale cross-reference:** after inlining the decision format, confirm no leftover reference to `docs/agents/decisions-format.md` (or any other repo-only file) remains anywhere in `to-prd/SKILL.md`. (Grep the file post-edit.)
2. **Commit check:** the commit message will state the reason ("docs-only: SKILL.md instruction fix, ADR 0063 exemption") so the direct-commit gate doesn't block it.

## Task List

1. Edit `skills/to-prd/SKILL.md` line 8: append the step-2 exception to the "Do NOT interview the user" sentence, per the ticket's exact wording.
2. Edit `skills/to-prd/SKILL.md` line 20: replace both "Check with the user" sentences with the module-sketch-confirmation + headless-skip-and-record text, inlining the one-line decision format (choice / options considered / why) instead of linking `docs/agents/decisions-format.md`, and dropping the "which modules get tests" question entirely.
3. Edit `skills/to-prd/SKILL.md`'s `## Testing Decisions` template (around line 68): replace bullet 1 with the break-it-bar wording citing `docs/north-stars.md` and ADR 0063; replace "Which modules will be tested" with "Which break-it cases matter most for each module."
4. Grep the edited file to confirm no reference to `docs/agents/decisions-format.md` (or other repo-only paths) remains, and re-read the whole file to check each of the four acceptance criteria literally holds.
5. Commit with a stated docs-only/ADR-0063-exemption reason (no test changes expected).