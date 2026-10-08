# Issue Tracker

**Type**: GitHub Issues
**Repo**: G-Eskayo/marvin (from `git remote -v`)
**CLI**: `gh` (must be authenticated — `gh auth status` to check)

## Conventions

- Create an issue: `gh issue create --title "..." --body "..." [--label ...]`
- Read an issue: `gh issue view <number>`
- Comment on an issue: `gh issue comment <number> --body "..."`
- List open issues: `gh issue list`
- Apply/remove labels: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`

## Consumer rules

- `to-issues` creates new issues via `gh issue create`; no project-board automation exists on
  this repo yet, so there's nothing else to add an issue to beyond the issue itself.
- `triage` reads open issues via `gh issue list` and applies labels from
  `docs/agents/triage-labels.md` — it does not invent label names not defined there.
- Never force-push, close, or delete issues without explicit user confirmation — these skills
  only create/comment/label by default.

## Which project a ticket belongs to (ADR 0060)

A ticket belongs to the project of the repo it's filed in. When the work is **for another project** but filed here
because its code lives here (the website's tools and map, the mobile backend), add that project's label:

- `project:portfolio-website-updater`: gileskayo.me pages, images, the website map, anything a site visitor sees
- `project:marvin-mobile`: the iPhone app and its backend
- any other: `project:<catalog id>` (ids from `~/.agents/venv/bin/python ~/.agents/lib/project_catalog.py show`)

Create a missing `project:` label with `gh label create` (description: "Work for <project>, filed here because its
code lives here (ADR 0060)"). An hourly tagger adds the label when a ticket clearly names another project, and lists
unclear ones for Gil; don't rely on it, label at filing time. Before starting a **new** project or board, check active
and archived boards and the catalog for one that already covers it (docs/plans/project-boards-2026-10-08.md).
