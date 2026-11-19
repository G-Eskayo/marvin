## North-star fit

- **Reuses:** the existing `<issue-template>` block in `skills/to-issues/SKILL.md` (lines 70-128) — this is a 4-line text swap inside a section that already exists, plus one sentence appended in the same prose style the template already uses elsewhere (e.g. the guidance paragraph above `## Recurrence check` at line 104). No new file, section, or mechanism.
- **Simplest sufficient approach:** a pure text edit. I verified there is no code path that parses or executes this template file — `lib/purpose_metrics.py` and its tests (`lib/tests/test_purpose_metrics.py`, `lib/tests/test_fit_check.py`) build their own inline `BODY` fixtures and never read `skills/to-issues/SKILL.md`. So nothing beyond the doc edit is needed, matching the ticket's own "Docs-only: exempt" classification.
- **Tokens:** trivial to make; saves tokens repeatedly — every future ticket this skill files stops carrying a copy-pasted stale baseline into its `## Purpose metric` section, which is the kind of compounding, one-fix/many-tickets leverage north star 4 (tool for tools) calls for.
- **More capable, not more passive:** removes a silent trap (an agent reusing a real historical number as if it were a placeholder) that otherwise corrupts Health's purpose-metric tracking without Gil ever noticing until an outcome check misfires on an unrelated ticket.

I checked the ticket's own "fit" claim against the code and it holds: `lib/purpose_metrics.py:outcome_gap()` (lines 865-866) already returns `"Check on is in the past: the check would measure before the fix ran"` for a backdated date — confirmed in the current file, no guard needs adding. I also re-ran the search the triage note claims was already done: `gh issue list --repo G-Eskayo/marvin --label purpose-metric --state all --search "14.3"` returns only #277 (the original headless-allowlist ticket) — no stale copies exist to fix. Both of the original ticket text's extra acceptance criteria are therefore already satisfied; the current (triage-adjusted) issue body correctly narrowed scope to just the template text, and I'm treating that top section as authoritative per the override rule (the `<details>` block is historical context, not live scope).

Scope boundary: the `## Recurrence check` section just below (lines 102-108) has the same "real-looking literal example" pattern (`ticket-planned-3x-in-24h` / `5` / a real date), but the ticket only asks for the `## Purpose metric` section — I'm leaving it untouched to avoid scope creep.

## Tests (first)

The ticket's "How we'll try to break it" section reads **"Docs-only: exempt"**, and its acceptance criteria are plain text assertions a diff can be checked against, not a parsed/executed path. I looked for any misuse the section might have missed (bad/malformed input, dependency failure, repeats/concurrency, stale state, permissions, a person's mistake) and found none apply: there is no code that reads this specific text at runtime, so there's no input to corrupt, no dependency to fail, and no concurrent writer. No automated test is being added or changed for this ticket — confirmed deliberate, not an oversight.

Verification instead of tests, done by direct inspection post-edit:
1. The four replaced lines are exactly the bracketed placeholders, no residual literal values (`headless-refusal-rate`, `14.3`, `-70%`, `2026-10-16`) anywhere in the file.
2. The new example line is present immediately after, worded as specified, and is clearly marked "format only, don't copy."
3. `rg` across the repo confirms `skills/to-issues/SKILL.md` was the only file holding this stale text (already run during planning).

No Decisions section: the ticket fully specifies the replacement text, and both of the original ticket's extra criteria are independently confirmed already satisfied — nothing here needs the owner's judgment call.

## Task List

1. Edit `skills/to-issues/SKILL.md` lines 97-100: replace the four literal-value lines with the four bracketed-placeholder lines given verbatim in the ticket (`[name registered in lib/purpose_metrics.py]`, `[value you measured, with date]`, `[absolute value or % change]`, `[YYYY-MM-DD, after the slice can have shipped]`).
2. Insert the format-only example/delete-instruction sentence immediately after those four lines, worded exactly as given in the ticket.
3. Re-read the edited section to confirm no stray real values remain and the `## Recurrence check` heading/content directly below is untouched.
4. No code, test, or other file changes — confirmed during planning that nothing else reads this template text and no stale copies or missing guards exist elsewhere.