# ADR 0060: Tickets belong to projects; a board is a project, not a repo

**Status:** Accepted (2026-10-08, Gil). Plan: `docs/plans/project-boards-2026-10-08.md`.

## Context

Boards were one repo's tickets. Work for one project is often filed in another project's repo because its code lives
there (the website's tools and map are in MARVIN's repo; the mobile backend too), so 22 of MARVIN's 97 open tickets
were really the website's or MARVIN Mobile's, and the website's own board looked nearly empty.

## Decision

- A ticket belongs to the project of its repo unless it carries `project:<catalog id>`.
- A project's board shows its repo's own tickets plus every registered repo's tickets labelled for it; a repo's board
  folds tickets labelled for other projects into one row.
- Labels are applied at filing time by rule (`docs/agents/issue-tracker.md`), and hourly by a deterministic tagger
  (`config/project_tags.json`) when the signal is unambiguous; ambiguous ones are listed for Gil. A Health check shows
  unlabelled tickets that look like another project's.
- A finished project (every ticket closed, no open PR, quiet 14 days) moves to Archived automatically; before creating
  any board MARVIN checks active and archived boards and the catalog for a match, and offers to reuse it (reopen, or a
  sub-project via `area:<sub>`).

## Consequences

- Code stays where it lives; the pipeline still builds the repo the code is in.
- One more label family to keep tidy; the tagger and the Health check exist so it doesn't depend on memory.
- Archived boards keep their history; nothing is deleted by archiving.
