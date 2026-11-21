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
- **Link vocabulary** (marvin#1004, #1016): tickets and PRs express relationships in their body text via link words.
  Every word supports `owner/repo#N` (or the issue's URL) for a ticket in another repo:

  | Word | Use | Inverse word |
  |------|-----|---|
  | `Closes` (Fixes, Resolves) | The PR finishes the ticket. GitHub closes it on merge. | `Closed by` |
  | `Part of` | The PR is a step (mock-up, stacked slice, plan, docs). The ticket stays open. | `Worked on in` |
  | `Blocked by` | This ticket cannot progress until another ticket is closed. | `Blocks` |
  | `Duplicate of` | This ticket is the same as another. | `Duplicated by` |
  | `Covered by` | This ticket's scope is included in another ticket's implementation. | `Covers` |
  | `Supersedes` | This ticket replaces another (in preference, design, or intent). | `Superseded by` |
  | `Related to` | This ticket is connected to another but doesn't strictly block or duplicate it. | `Related to` |

  - **For PRs, only Closes and Part of** are gated (marvin#1004): every PR body in a board repo must name its ticket
    via `Closes #N` (the PR finishes the ticket) or `Part of #N` (the PR is a step). When `Part of #N` names a red
    ticket (main-red label, or bug+p0 titled "Main red"), `bin/gh` prints a warning that main merges are blocked
    (marvin#1147). "for #N" or a bare "#N" links nothing. `bin/gh` refuses `pr create` and `pr edit --body*` when
    the body names no ticket either way (`PR_NAMES_NO_TICKET`, `lib/pr_ticket_check.py`); `MARVIN_NO_TICKET="<reason>"`
    lets one call through, logged.
  - **For tickets, all seven words are parsed** to populate the Related panel and dependency graphs (marvin#1016).
    Conflicts resolve by priority: Closes > Part of > Blocked by > Duplicate of > Covered by > Supersedes > Related to
    (a ticket named `Closes #5` and `Duplicate of #5` is treated as closes). Same word, same ticket, same repo: one ref.
    A ticket's own body saying "Blocked by #N" (itself) is never a blocker (openDependencies guards against self-reference).
  - Write the full form `owner/repo#N` or paste the issue's URL (`https://github.com/owner/repo/issues/N`) for a ticket
    in another repo. The ticket's board card shows **In review** with the PR on it (Closes/Part of only), and the
    dashboard's parity check is satisfied (PRs only). The Related panel and board dependency columns show cross-repo
    links when resolved, with the target's repo name shown as a chip (Decision cross_repo_depth: A, shallow).
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
