I have all the evidence I need. Now, writing the plan.

## North-star fit

**Reuses:** the decisions-format pattern (`docs/agents/decisions-format.md`) was checked but isn't needed — every open item resolves from evidence already in the repo/venv, so no owner choice is required. No new file, script, or abstraction is created; this is a direct edit to existing prose in `skills/resume-tailor/docs/design.md`, following the exact edit the ticket specifies.

**Simplicity:** the ticket already prescribes the replacement text and the evidence-gathering rule verbatim ("mark done only if ... otherwise mark 'not blocking'"). There is no design choice to make — just verifying each piece of evidence against the real filesystem and writing it down. Nothing simpler exists than making the stale doc match reality.

**Tokens:** cheap — one file, ~10 lines changed, no code, no tests to run (ticket explicitly marks this "Docs-only: exempt"), no scripts executed beyond read-only verification.

**North star 3 (human experience):** directly serves it — a future session (human or agent) reading `design.md` will no longer be misled into re-doing finished setup work. No automation is removed from the user; this is pure doc-accuracy upkeep, leaving nothing more passive.

**Machine:** no execution needed beyond file edits and read-only checks already done in this worktree; no machine-selection question arises.

## Evidence gathered (verified before writing the plan)

- `README.md`: repo is public, code-only, "In use since July 2026 ... 12 real applications" → **repo created**, tool in active use.
- `docs/architecture.md`: 11 ADRs (ADR-001 through ADR-011) spanning 2026-06-29 to 2026-07-02, including ADR-006 superseding ADR-002, ADR-010 (font), ADR-011 (visual hierarchy) → **template approved**, with real post-launch revision history.
- `~/.agents/venv/lib/python3.11/site-packages/weasyprint-69.0.dist-info/METADATA` exists, and `~/.agents/venv/bin/weasyprint` is wired to `weasyprint.__main__` → **WeasyPrint install confirmed**, matches the ticket's cited evidence exactly (69.0).
- `~/.claude/resume/master.md` does not exist in this environment (`Glob`/`Read` both report nothing) → **Resumes uploaded**, **Transcript uploaded**, and **Location** cannot be confirmed by the specified method. Per the ticket's own fallback ("otherwise mark 'not blocking: tool in use'"), these three resolve to that label — this is not an open design choice, it's the ticket's own specified default when the signal isn't present.
- No personal data (names, addresses, schools, employers) will be copied into the doc anywhere — all evidence above is repo-structural or venv-only, satisfying the "no personal details" acceptance criterion by construction.

No **Decisions** section is needed: nothing here requires the owner to choose between options: the ticket's instructions plus the evidence fully determine every edit.

## Task List

1. Edit `skills/resume-tailor/docs/design.md` line 5: replace `**Status:** Draft — awaiting template approval and resume/transcript uploads` with `**Status:** Implemented. Post-launch revisions are recorded as ADRs in architecture.md.`
2. Edit line 349 heading: `## 9. Open Items (resolve before implementation)` → `## 9. Open Items (at design time)`.
3. Edit the **Template approved** item (line 351): check it, evidence `template/resume.css in use, ADR history (ADR-002 superseded by ADR-006; ADR-007–011)`.
4. Edit the **Resumes uploaded** item (line 352): mark `not blocking: tool in use`.
5. Edit the **Transcript uploaded** item (line 353): mark `not blocking: tool in use`.
6. Edit the **Location** item (line 354): mark `not blocking: tool in use`.
7. Edit the **WeasyPrint install confirmed** item (line 355): check it, evidence `venv has weasyprint 69.0`.
8. Leave the **Font decision** item (line 356) untouched (already `[x]`).
9. Edit the **Repo created** item (line 357): check it, evidence ``G-Eskayo/resume-tailor` exists, public``.
10. Re-read the full diff once to confirm: Status line no longer says "Draft", no bare unchecked box remains in §9, and no personal detail was introduced — satisfying all three acceptance criteria.

No automated tests are added, per the ticket's own "How we'll try to break it: Docs-only: exempt."