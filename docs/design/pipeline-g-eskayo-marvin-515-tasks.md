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