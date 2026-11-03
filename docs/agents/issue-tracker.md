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
- **Every ticket starts with `## Task and purpose`** (Gil, 2026-10-30): Task, Purpose and North star, one line each
  (`skills/to-issues/SKILL.md` template). That includes the quick ones an agent files for itself in the middle of a
  session, which skip the rest of the template. It steers the build, so keep it to the three lines. A `bug` still
  needs its outcome check (`docs/agents/triage-labels.md`).
- **A PR names its ticket** (Gil, 2026-11-02, marvin#1004): every PR body says which ticket it is for, in one of two
  ways, on a line of its own:
  - `Closes #N` (or Fixes/Resolves): the PR finishes the ticket. GitHub closes the ticket when the PR merges.
  - `Part of #N`: the PR is a step towards the ticket: a mock-up, a stacked slice, a plan, docs. The ticket stays open.

  Write `owner/repo#N` (or paste the issue's URL) for a ticket in another repo, e.g. a private instance PR for a public
  engine ticket: `Closes G-Eskayo/marvin#623`. Either way the ticket's board card shows **In review** with the PR on it,
  and the dashboard's parity check is satisfied. "for #N" or a bare "#N" links nothing. `bin/gh` refuses
  `pr create` and `pr edit --body*` in a repo with a MARVIN board when the body names no ticket either way
  (`PR_NAMES_NO_TICKET`, `lib/pr_ticket_check.py`); `MARVIN_NO_TICKET="<reason>"` lets one call through, logged, for a
  PR that truly has no ticket.
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
unclear ones for Gil; don't rely on it, label at filing time. A ticket that only *mentions* other projects (e.g. a
tool that works across all of them) gets this repo's own label, `project:marvin`, which the tagger leaves alone. The
tagger's signals are in `config/project_tags.json`; a new project is a new entry there. Before starting a **new** project or board, check active
and archived boards and the catalog for one that already covers it:
`~/.agents/venv/bin/python ~/.agents/lib/board_registry.py similar "<what the project is>"`. A `CLOSE` match means
reopen or extend that one (`project:<id>` + `area:<sub>`) unless Gil says it is separate; `board_registry.py ensure`
refuses a new board with a close match unless given `--new` (docs/plans/project-boards-2026-10-08.md).
