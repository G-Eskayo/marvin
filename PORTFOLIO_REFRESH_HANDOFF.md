# MARVIN Portfolio Refresh (#840) — Handoff Summary

## What's Ready

The updated portfolio content for gileskayo.me/ai-projects/marvin/ is complete and verified.

**File:** `content/longform/marvin.json`

✅ **Quality checks passed:**
- Privacy clean (no private names, emails, paths, hostnames)
- Voice matches your portfolio register (direct, confident, proof-focused; short sentences; no hedging)
- All claims traceable to sources (repo PRs, ADRs, git logs)
- JSON structure valid and ready for `portfolio_longform.py`

## What Changed in the Content

### Shipped (newly emphasized):
- **Multi-Mac peer care** (Nov 24) — Macs notice when each other goes down, fix what they can, call owner for human decisions
- **Mail sorting** (Nov 7–24) — Watches Gmail in real time (IDLE) and iCloud via IMAP; each account independent
- **Local model consolidation** (Oct 21) — Halved token spend on research tasks
- **Revamped merge gate** (Oct–Nov) — Time and space complexity regressions are must-fix, measured live

### In-design (clearly marked as such):
- **MARVIN Mobile** — Architecture decided (ADRs 0039–0046); no code shipped; native iPhone app with Voice/Chat/Dashboard surfaces
- **Voice** — ADR 0075 proposed; ticket #670 open; one endpoint, three ways in (Siri doorway, Mac loop, iPhone surface)

### Honest status:
- Runs on macOS ARM; Intel and Linux untested
- Dashboard macOS-only (launchd, Electron)
- Source public on GitHub; secrets private via self-hosted git sync

## What Remains (Deployment Steps)

All work happens on the primary development machine (`~/portfolio-dev` dev site).

### 1. Dry-run to see what will happen
```bash
~/.agents/venv/bin/python lib/portfolio_longform.py \
  'https://gileskayo.me/ai-projects/marvin/' \
  --author content/longform/marvin.json \
  --plan
```

### 2. Backup the current state
```bash
~/.agents/venv/bin/python lib/portfolio_longform.py \
  'https://gileskayo.me/ai-projects/marvin/' \
  --rollback
```
Saves the current page to `~/.claude/outbox/migrations/marvin/` before authoring. If the new content needs to be reverted, run `--rollback` again after `--author` to restore the page to this pre-authoring snapshot.

### 3. Author the new content
```bash
~/.agents/venv/bin/python lib/portfolio_longform.py \
  'https://gileskayo.me/ai-projects/marvin/' \
  --author content/longform/marvin.json
```

### 4. Validate on dev site
```bash
~/.agents/venv/bin/python lib/portfolio_sync_dev.py
```
Should show zero errors (warnings OK).

### 5. Capture screenshots at spec'd widths
```bash
~/.agents/venv/bin/python lib/portfolio_imagegen.py \
  --page 'https://gileskayo.me/ai-projects/marvin/' \
  --widths 860,1440 \
  --output ~/.claude/outbox/marvin-screenshots/
```

### 6. Visual check
- Open both screenshots at 860px and 1440px
- Verify no text cut-off, no overflow, images load
- Run privacy check (no unblurred sensitive info)

### 7. Confirm no production push
```bash
cd ~/portfolio-dev
git status
# Verify no deploy/ changes in unpushed commits
if git diff --name-only origin/main..HEAD | grep -q deploy/; then
  echo "ERROR: deploy/ changes detected in unpushed commits"
  exit 1
fi
```
`git status` should be clean (no uncommitted changes). The diff check ensures no deploy/ paths in unpushed commits. Shipping to production stays your manual step.

## If Something Breaks

**Instant rollback:**
```bash
~/.agents/venv/bin/python lib/portfolio_longform.py \
  'https://gileskayo.me/ai-projects/marvin/' \
  --rollback
```
Running `--rollback` after `--author` restores the page to the snapshot saved before authoring (from step 2 above). This saves a new snapshot but then reverts the page content to the pre-authoring version.

## Evidence & Sources

Every claim in the content traces to:

- **Recent PRs merged:** 2026-11-07 to 2026-11-24 (`gh pr list --state merged --limit 20`)
- **ADRs 0039–0046 (Mobile):** Accepted status
- **ADR 0075 (Voice):** Proposed status, ticket #670 open
- **Multi-Mac PR #1413:** Merged 2026-11-24
- **Mail sorting PRs #1407, #1410, #1412:** Merged 2026-11-07–11-24
- **Local model PR #1408:** Merged 2026-11-24
- **System:** Version 0.86.1, 34 skills, running on two Macs

**Documentation:**
- `docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md` — every claim mapped to source
- `docs/design/pipeline-g-eskayo-marvin-840-deployment.md` — exact deployment steps

## Files in This Worktree (Uncommitted)

```
content/longform/marvin.json                               (the content)
docs/design/pipeline-g-eskayo-marvin-840.md               (the plan)
docs/design/pipeline-g-eskayo-marvin-840-tasks.md         (task list)
docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md (sources)
docs/design/pipeline-g-eskayo-marvin-840-deployment.md    (steps)
docs/design/pipeline-g-eskayo-marvin-840-summary.md       (work summary)
```

These stay uncommitted. The pipeline process will handle commit/push after you run the deployment steps and visually approve.

## Blockers I Hit

SSH to the development machine was not available in don't-ask mode, so I prepared all content and documentation but couldn't run the actual deployment tools. This is correct — you should review the content before it ships anyway.

Everything you need is in this worktree. The deployment steps are copy-paste ready.

---

**Next:** Run the 7 deployment steps above on your development machine, then visually check the page. If clean, it's ready for production push.
