# Issue Tracker: Local Markdown

Seed template for `docs/agents/issue-tracker.md` when the repo has no remote issue tracker —
good for solo projects or repos without a GitHub/GitLab remote.

```markdown
# Issue Tracker

**Type**: Local markdown
**Location**: `.scratch/<feature-slug>/`

## Conventions

- Create an issue: make a new directory `.scratch/<feature-slug>/` with an `ISSUE.md` file
  containing title, description, and any acceptance criteria — same content an issue would have
  on GitHub, just as a file.
- An issue is "open" if `.scratch/<feature-slug>/ISSUE.md` exists and has no `Status: closed` line
  at the top; "closed" otherwise (don't delete closed issues — mark them closed instead, so
  history is preserved).
- Comment on an issue: append a dated `## Update — YYYY-MM-DD` section to `ISSUE.md` rather than
  creating a separate file — keeps the whole history in one place.
- List open issues: `grep -L "Status: closed" .scratch/*/ISSUE.md`
- Labels: a `Labels:` line at the top of `ISSUE.md`, comma-separated, matching
  `docs/agents/triage-labels.md`.

## Consumer rules

- `to-issues` creates a new `.scratch/<slug>/ISSUE.md` rather than calling any external CLI.
- `triage` reads `Status:`/`Labels:` lines the same way it would read GitHub/GitLab labels —
  same five canonical roles, just stored as plain text instead of tracker metadata.
- Nothing here should be pushed anywhere automatically — `.scratch/` is local-only by
  convention; if the repo wants these tracked in git, say so explicitly (don't assume).
```
