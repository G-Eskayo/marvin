## North-star fit

Reuses the exact pointer pattern SKILL.md already uses for criteria.md itself (`skills/readme/SKILL.md:10-12`, "The criteria... are in [`docs/readme-criteria.md`](../../docs/readme-criteria.md): read it once per session... This skill is the procedure; the criteria are the standard.") — a one-line cross-reference instead of a copy. No new file is created; the existing three files (`docs/readme-criteria.md`, `skills/readme/TEMPLATES.md`, `skills/readme/SKILL.md`) absorb the change. This is the simplest sufficient fix — North star 1 (minimise resources): it removes ~300 tokens of duplicated prose loaded on every readme run and collapses two drift-prone edit sites into one (the App profile's "platform support" line already drifted — verified below, confirming the ticket's claim). It is a pure build-time/token efficiency change with no effect on what a user sees or does, so it neither adds nor removes user capability (north star 3 doesn't apply either way). Runs locally, no machine-placement question (docs edit only).

I checked the ticket's own "North-star fit" claim against the code: accurate. I also independently verified its two "Verified" footnotes:
- `lib/readme_audit.py` (`lib/readme_audit.py:63-77`, `lib/tests/test_readme_audit.py`) parses only generic Markdown structure (headings, links, images, code blocks, paragraphs) — nothing keys off the `## Profiles` or `## What a program cannot judge` headings or text, and no test references them.
- No `#profiles` anchor exists anywhere in the repo (checked via grep).

## Diff check (acceptance criterion 2), done by hand now so the task list is concrete

Comparing `docs/readme-criteria.md`'s `## Profiles` (lines 70-80) against `skills/readme/TEMPLATES.md`'s five templates:
- **App / desktop or iOS**: criteria says "...status and platform support, link to docs and issues." TEMPLATES' App section (`skills/readme/TEMPLATES.md:25`) has "**Docs** (links), **Roadmap/status**, **Contributing**, **License**" — missing explicit **platform support** (confirms the ticket's flagged gap) and an explicit **issues** link. Both need folding into TEMPLATES before the criteria copy is removed.
- **Library/CLI, Claude Code skill/agent tooling, Research/coursework, Infrastructure (MARVIN)**: every detail in the criteria copy is already present (same or more detail) in the corresponding TEMPLATES.md section. Nothing else to fold in.

Comparing `## What a program cannot judge` (lines 82-86) against SKILL.md's "The review step" (`skills/readme/SKILL.md:58-66`): all five criteria questions (one-liner specificity, diagram explain-vs-decorate, quickstart on a clean machine, numbers still true, stranger's trust) are already covered by SKILL.md's six review questions (which also adds one criteria.md lacks: honesty about what's not built). Nothing to fold in — a straight pointer replacement is correct.

## Tests (ticket's "How we'll try to break it" says "Docs-only: exempt" — no adversarial test cases apply to a three-file prose edit; listing the verification I'll run in place of break-it tests, plus the one case the exemption doesn't excuse)

1. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_readme_audit.py` before and after the edit — confirms acceptance criterion 4 (no regression) and that the exemption is warranted (no test exercises the removed prose).
2. Hand-diff `## Profiles` against `TEMPLATES.md` post-edit (reusing the comparison above) to confirm every criteria-only detail (platform support, issues link) landed in TEMPLATES.md before the section is collapsed to a pointer — satisfies acceptance criterion 2 and is the actual misuse case a docs-only exemption doesn't excuse: *deleting unique content instead of moving it* is the one way this "exempt" change could still silently lose information.
3. Grep the whole repo for `#profiles` and for other inbound links to the two sections being pointerized, repeated after the edit, to confirm nothing is left dangling (covers acceptance criterion 5, and the "wrong order" misuse case: editing SKILL.md's pointer before TEMPLATES.md actually has the folded-in content would leave a moment of truth-drift — sequencing the task list to avoid that).
4. Manually dry-run the SKILL.md workflow's step 3 against one real repo profile (e.g. this repo, "Infrastructure/system") to confirm picking a profile from TEMPLATES.md alone (no criteria-doc lookup) still produces the same section order and content as before — satisfies acceptance criterion 6 from the ticket's original text (profile selection and review questions still work after the change).

No Decisions section is needed: the ticket is fully specified, scoped to three known files, and the one ambiguity (the "issues" link gap) is resolved by the straightforward rule "fold in whatever the criteria copy had that TEMPLATES.md lacks," not a design choice for the owner.

## Task List

1. In `skills/readme/TEMPLATES.md`'s App template (around line 25), fold in the App profile's "platform support" and "link to...issues" details from `docs/readme-criteria.md`'s `## Profiles` App bullet, without disturbing the other four templates (already complete).
2. In `docs/readme-criteria.md`, replace the `## Profiles` section body (lines 70-80) with a one-line pointer to `skills/readme/TEMPLATES.md`, matching the pointer style SKILL.md already uses for the criteria doc.
3. In `docs/readme-criteria.md`, replace the `## What a program cannot judge` section body (lines 82-86) with a one-line pointer to the review step in `skills/readme/SKILL.md`.
4. In `skills/readme/SKILL.md` step 3 (lines 37-38), change "from the criteria doc and start from TEMPLATES.md" to cite only `TEMPLATES.md` for profile selection.
5. Run `lib/tests/test_readme_audit.py` and the repo-wide greps from the test list above to confirm no regression and nothing is left dangling.
6. In the PR description, list the diff-checked-by-hand profile comparison (step 1's findings) as required by acceptance criterion 2.