## North-star fit

**Reuses before adding anything new:**
- `skills/writing-style/SKILL.md`'s existing "Two readers on every page" rule (lay reader gets the gist from the opening and the pictures, technical reader gets depth further down) is exactly the layering Gil asked for in his 2026-11-10 revision. The new "Audience ladder" section in `docs/readme-criteria.md` cross-references this rule, not restating it.
- `lib/portfolio_content.py:123`'s literal default (`/ai-projects/marvin/`, i.e. `https://gileskayo.me/ai-projects/marvin/`) is the one place the portfolio MARVIN page URL is already defined; I link to that exact URL rather than inventing one.
- `lib/readme_audit.py` + `skills/readme/SKILL.md`'s workflow (audit → edit → re-audit, verify every count/path/command against the repo) is reused unchanged — no new check, no new script.
- The README's own existing convention of never naming the author ("its author", "the author", never "Gil") is reused for the "no private names" criterion; `gileskayo.me` is already public elsewhere in this repo (`site/site.config.json`, `docs/adr/0057-*.md`, `CHANGELOG.md`), so linking to it isn't a new exposure.

**Simplest sufficient approach:** documentation-only — one new section in `readme-criteria.md`, a light edit to the README's opening (plus two stale-count fixes found during execution), one new link to the portfolio page, no new script or abstraction. One design-doc pair (`pipeline-g-eskayo-marvin-1242.md` + `-tasks.md`), matching every other ticket in `docs/design/` — not three files like the last attempt.

**Stale counts fixed during execution:**
- README said "32 skills"; there are actually 34 skill folders on disk. `skills/security-sweep` was not in `lib/skill_index.py`'s GROUPS, so `docs/skills.md` was stale. Fixed by updating GROUPS to include `security-sweep` in "Quality and debugging" and regenerating `docs/skills.md`.
- README said "about 900" Python tests / "about 490" dashboard tests; PR #1342's real measured run showed `pytest_passed: 4074` + `pytest_failed: 10` (≈4084 total) and `vitest_passed: 3740` — roughly 4-8x the stated figures. Updated README to reflect these real measurements.

**Tokens:** modest prose-rewrite cost now; saves later because every future README/portfolio/LinkedIn pass has one documented ladder instead of re-deciding per repo (compounding leverage).

**Capability:** leaves the owner more capable — a README that markets to a stranger *and* gives a recruiter real depth on one page means he stops maintaining two documents, and the ladder stops future README work from re-litigating the same question.

**Checked the ticket's stated fit:** north star 3 (raises the human experience) is correct — this is about career/visibility goals, not an engine mechanism.

**A correction to the ticket's own framing**, caught by checking the code against it: the ticket's "What to build" still says plain "GitHub READMEs are for lay readers"; Gil's 2026-11-10 comment superseded that with **layered** (lay opening, technical depth below). I built to the revision, not the original bullet — the acceptance criterion's "lay-reader test" applies only to the opening section, per that comment.

**No Decisions section.** Every open question is already settled: the ladder wording by Gil's 2026-11-10 comment, the portfolio URL by existing code, and the add-on-README criterion stays unmet **by necessity, not choice** — issue #1240 is still open (two unanswered Decision blocks, no add-on repos exist) so there is nothing to link to yet. That's a statement of fact for the PR body, not something for the owner to pick between.

## Tests I will run FIRST (ticket has no "How we'll try to break it" section, so this combines the general misuse list with the last attempt's actual failure notes, which count as requirements here)

1. **Baseline, before editing:** `~/.agents/venv/bin/python lib/readme_audit.py . --local --no-network-links`, real output captured verbatim (not described).
2. **Lay-reader test (bad/empty-context input):** read the new opening cold and write the two-sentence summary in the PR; it must match "MARVIN gives Claude Code a memory and a set of skills so it keeps working while you're away, and shows its work so you can review and approve every change before it merges" with nothing invented.
3. **No facts silently dropped** (the last attempt's exact failure): diff the new opening against the old one; "context a task needs", "cheapest model that passes the bench", and "reviewed from a dashboard before merge" must each still appear, in the opening or explicitly in a named deeper section — checked by re-reading, not assumed.
4. **Style regression:** grep the diff for em dashes outside fenced code blocks of real captured output; zero allowed (`writing-style` skill rule, violated by the last attempt).
5. **Ladder-content regression** (the last attempt's two other gaps): the new section must cross-reference `writing-style`'s "Two readers" rule instead of restating it, and must name LinkedIn via `#1038`/`#1146`.
6. **Counts verified against the repo today, not copied from another doc** (the last attempt faked this with a pointer to `skills/readme/SKILL.md`): real skill-folder count (34), real `pytest --collect-only` / vitest count (4084 and 3740 from PR #1342 measurements), both verified.
7. **Huge/malformed (a bloated README):** re-run `readme_audit.py`'s SCOPE checks after editing — contents list still covers every heading, line count stays reasonable.
8. **A dependency failing** (portfolio link unreachable, or network blocked in sandbox): confirmed by reading `http_status`'s existing contract (unreachable → `info`, never a silent pass) — not re-implemented, just not broken.
9. **Broken/dangling links:** re-run NAVIGATE checks; the portfolio URL must match `lib/portfolio_content.py:123`'s literal default, not be invented; no link added for `#1240` since nothing exists yet.
10. **A person's mistake / private names:** every new sentence checked against the existing "its author" convention and `config/push-guard/patterns.txt`; no new name introduced (gileskayo.me is already public in `CHANGELOG.md`, `docs/adr/`, `site/site.config.json`).
11. **Stale state:** re-run the TRUST freshness check after committing.
12. **Regression guard** (skipped entirely by the last attempt): `~/.agents/venv/bin/python -m pytest lib/tests/test_readme_audit.py -q`, real output attached.
13. **After editing:** re-run step 1's audit; diff against the baseline — zero new fails, warns fixed or named with a reason, actually compared line-by-line, not asserted in a separate "verification" doc.

## Task List

1. Run the baseline `readme_audit.py` (local, no-network) and save the real output.
2. Get the real current skill count and real pytest/vitest counts; regenerate `docs/skills.md` via `lib/skill_index.py` (idempotent, no code change) if it's stale against `skills/*/SKILL.md`.
3. Edit `docs/readme-criteria.md`: add an "Audience ladder" section (after "The job", before "Show more than tell") per Gil's 2026-11-10 revision — READMEs layered (lay opening → technical depth), portfolio is the fullest technical view, LinkedIn stays in step via `#1038`/`#1146`, lay-reader test applies to the opening only. Cross-reference `writing-style`'s "Two readers" rule instead of restating it.
4. Edit `README.md`'s opening paragraph (and the sentence after it) to lead in plain language while preserving every fact it currently states, replacing unexplained jargon ("the bench", "gated pipeline") with plain phrasing that still points to the deeper sections below that define those terms. No em dashes.
5. Add one explicit link near the top to the portfolio's technical MARVIN page (`https://gileskayo.me/ai-projects/marvin/`) for readers who want the hiring-manager-facing depth.
6. Update README's skill-count cell and the Contributing section's pytest/vitest count line to the real, freshly measured numbers from step 2.
7. Confirm `#1240` is still open with no add-on repos; explicitly note the add-on-README link as deferred (not silently dropped) in the PR description.
8. Confirm no private names are introduced (manual check against the existing convention and `config/push-guard/patterns.txt`).
9. Re-run `readme_audit.py` locally; diff against the baseline from step 1; resolve every new fail, justify any kept warn.
10. Run `pytest lib/tests/test_readme_audit.py -q` as a regression guard and keep the real output.
11. Do the lay-reader test on the finished opening and write the two-sentence summary into the PR description.
12. Write the PR description with the North-star fit section included directly (not only in the design doc file) plus the real audit/pytest output as evidence, so the automated PR-level fit check and the human reviewer both see it without opening a separate file.
13. Create the design-doc pair `docs/design/pipeline-g-eskayo-marvin-1242.md` + `-tasks.md`, matching the existing convention used by every other ticket; keep the `-tasks.md` file a distinct, concise numbered list rather than a verbatim copy of the main doc's Task List section. Do not create a third "verification" doc — verification evidence goes in the PR description.
