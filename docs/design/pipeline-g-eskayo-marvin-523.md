Confirmed both functions exist and behave as described. Now I have everything to write the plan.

## North-star fit

This reuses the exact check function names already defined in `lib/session_start_report.py` (`check_auto_fix_log`, `check_suggestions`, `process_and_check_quarantine`) and `docs/session-start-checklist.md`'s existing table as the source of truth — no new code, no new file, no new abstraction. It's the simplest sufficient approach: four targeted text edits in three existing files, verified by a grep the ticket already specifies. It spends essentially no tokens beyond the edits themselves and saves future tokens/debugging time by removing a self-contradicting trap in the one skill whose job is catching exactly this kind of drift (north star 4: tool for tools — instructions that stay correct when the thing they point at changes). It leaves the user more capable: the fix removes a latent trust hazard (a stale pointer that silently misleads whoever next reorders Session Start), it doesn't make any decision for them or remove any judgment they'd otherwise exercise.

No ADR or CONTEXT.md decision argues against this; `docs/adr/0015` is being corrected in prose only (a stale internal cross-reference), not having its recorded decision changed — the historical "Fix 3" narrative still reads correctly, it just points at the quarantine check by name instead of by a now-ambiguous step number.

**Scope correction to the ticket's own "What to build":** the ticket's grep-everywhere instruction surfaces one reference it didn't anticipate: `docs/adr/0015-quarantine-review-feedback-loop.md:72` ("Wired into CLAUDE.md's session-start step 5 ...") also matches `session.start step [0-9]` and must be fixed for the acceptance criterion to pass — the ticket's two enumerated bullets don't cover it, but its third bullet ("grep ... for any other ... reference") does. I confirmed `docs/session-start-checklist.md` itself does **not** match the regex, so it needs no edit, consistent with the ticket's "its own step numbers stay" note.

## Tests

Docs-only change; the ticket explicitly marks this exempt from new test files ("Docs-only: exempt (the grep above is the check)"). The verification *is* the two acceptance-criteria greps, which I'll run after editing, not a new pytest:
1. `rg -i "session.start step [0-9]" skills docs lib` → must return no matches (covers: the two SKILL.md lines, the sort_suggestions.py line, and the ADR line found above).
2. For each replaced line, confirm by inspection that the named check (`check_auto_fix_log`, `check_suggestions`, `process_and_check_quarantine`) actually exists in `lib/session_start_report.py` — already confirmed during planning (lines 202, 255, 316).

No code path, input, dependency, concurrency, or permission surface changes, so there's no additional misuse case to cover beyond the grep the ticket specifies.

## Task List

1. Edit `skills/audit/SKILL.md` line 58: replace "Session Start step 8 already surfaces this." with wording naming the check — "the session-start report's auto-fix-log check (`check_auto_fix_log` in `lib/session_start_report.py`) already surfaces this."
2. Edit `skills/audit/SKILL.md` line 59: replace "Session Start step 2 already surfaces the pending count." with "the session-start report's suggestions check (`check_suggestions` in `lib/session_start_report.py`) already surfaces the pending count."
3. Edit `skills/architecture-review/scripts/sort_suggestions.py` line 42 (`DEFAULT_HEADER`): replace "CLAUDE.md session-start step 2" with a check-named reference, e.g. "the session-start report's suggestions check, `check_suggestions` in `lib/session_start_report.py`".
4. Edit `docs/adr/0015-quarantine-review-feedback-loop.md` line 72: replace "CLAUDE.md's session-start step 5" with "CLAUDE.md's session-start quarantine-review check (`process_and_check_quarantine` in `lib/session_start_report.py`)".
5. Run `rg -i "session.start step [0-9]" skills docs lib` and confirm zero matches.
6. Re-read each edited line in context to confirm it still reads naturally and each named function/check genuinely exists in `lib/session_start_report.py`.