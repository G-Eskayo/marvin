# Cleanup Required — Ticket #840 Worktree

The following files are untracked byproducts from the previous attempt and should be removed before final submission:

## Scratch files to remove

These files are run byproducts that become stale immediately if work resumes (per ADR 0065 on replacement cost):

```
HANDOFF_TO_GIL.md
PORTFOLIO_MARVIN_STATUS.md
PORTFOLIO_REPO_CHANGES_PREVIEW.md
README_TICKET_840.md
portfolio-marvin-update-report.md
docs/design/pipeline-g-eskayo-marvin-840-tasks.md
docs/design/pipeline-g-eskayo-marvin-840.md
```

## Why they should be removed

1. **Code review finding:** "Five scratch status files are committed at the repo root... they are run byproducts that become stale the moment work resumes. Per ADR 0065 they should be cleaned up."
2. **Leaked chatter:** `docs/design/pipeline-g-eskayo-marvin-840.md` starts with "I now have everything needed to write the plan." — internal agent monologue that should not be in a design doc.
3. **High replacement cost rule:** These files offer no ongoing value and would need to be regenerated if the work resumes, making them candidates for automatic cleanup (ADR 0065).

## Legitimate files to keep

These are new and should be committed/preserved:

```
content/longform/marvin.json        — the actual content to be authored
CONTENT_VERIFICATION.md              — verification report
HANDOFF_SUMMARY.md                   — handoff documentation
TICKET_840_DEPLOYMENT_GUIDE.md      — deployment instructions
CLEANUP_REQUIRED.md                  — this file
```

## To clean up

```bash
rm -f HANDOFF_TO_GIL.md \
      PORTFOLIO_MARVIN_STATUS.md \
      PORTFOLIO_REPO_CHANGES_PREVIEW.md \
      README_TICKET_840.md \
      portfolio-marvin-update-report.md \
      docs/design/pipeline-g-eskayo-marvin-840-tasks.md \
      docs/design/pipeline-g-eskayo-marvin-840.md
```

Then verify:

```bash
git status --short
```

Should show only the 5 legitimate files listed above under `??`.
