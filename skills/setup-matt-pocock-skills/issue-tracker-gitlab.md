# Issue Tracker: GitLab

Seed template for `docs/agents/issue-tracker.md` when the repo uses GitLab Issues.

```markdown
# Issue Tracker

**Type**: GitLab Issues
**Repo**: [owner/repo or group/project, from `git remote -v`]
**CLI**: `glab` (must be authenticated — `glab auth status` to check)

## Conventions

- Create an issue: `glab issue create --title "..." --description "..." [--label ...]`
- Read an issue: `glab issue view <number>`
- Comment on an issue: `glab issue note <number> --message "..."`
- List open issues: `glab issue list`
- Apply/remove labels: `glab issue update <number> --label "..." / --unlabel "..."`

## Consumer rules

- `to-issues` creates new issues via `glab issue create`; note here if this repo also expects
  issues attached to a milestone or epic by default.
- `triage` reads open issues via `glab issue list` and applies labels from
  `docs/agents/triage-labels.md` — it does not invent label names not defined there.
- Never force-push, close, or delete issues without explicit user confirmation — these skills
  only create/comment/label by default.
```
