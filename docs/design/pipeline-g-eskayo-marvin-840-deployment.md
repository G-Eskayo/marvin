# MARVIN Portfolio Refresh (#840) — Deployment Guide

## Content Prepared

**File:** `content/longform/marvin.json`

Updated portfolio long-form content for gileskayo.me/ai-projects/marvin/ with:
- Fresh factual claims sourced from recent PRs, ADRs, and system state
- Voice rewritten in Gil's direct, confident style (short sentences, proof-focused, no hedging)
- Honest status on what's shipped (Memory, 34 skills, Dashboard, Ticket pipeline, Mail sorting, Multi-Mac peer care)
- Honest status on what's in design (MARVIN Mobile, Voice — ADRs decided but no code shipped)

**Verification completed:**
- ✓ JSON structure valid
- ✓ Privacy check: no private names, emails, paths, hostnames
- ✓ All claims traceable to sources (repo, PRs, ADRs, git logs)
- ✓ Content voice matches Gil's portfolio register (direct, confident, proof-based)
- ✓ No AI-writing patterns (em-dash overuse, throat-clearing, hedging, intensifiers)

## Deployment Steps

### On the development machine (dev site deployment)

The dev site runs at `~/portfolio-dev`. All commands below run there.

**Important:** All commands assume `cwd = ~/portfolio-dev`. If running from elsewhere, prepend `cd ~/portfolio-dev &&` to each command.

1. **Plan the authoring step** (dry run, shows what will happen):
   ```bash
   cd ~/portfolio-dev
   ~/.agents/venv/bin/python lib/portfolio_longform.py \
     'https://gileskayo.me/ai-projects/marvin/' \
     --author content/longform/marvin.json \
     --plan
   ```

2. **Rollback backup** (saves the current state before authoring):
   ```bash
   ~/.agents/venv/bin/python lib/portfolio_longform.py \
     'https://gileskayo.me/ai-projects/marvin/' \
     --rollback
   ```
   This writes the before-longform state to `~/.claude/outbox/migrations/marvin/`.

3. **Author the new content** (applies the update):
   ```bash
   ~/.agents/venv/bin/python lib/portfolio_longform.py \
     'https://gileskayo.me/ai-projects/marvin/' \
     --author content/longform/marvin.json
   ```

4. **Run the portfolio pipeline** (sync, regenerate, capture, evaluate):
   ```bash
   ~/.agents/venv/bin/python lib/portfolio_sync_dev.py
   ```
   This validates the page against the evaluator and writes results to `~/.claude/portfolio/pipeline-status.json`.

5. **Capture scrolled screenshots** at the spec'd widths:
   ```bash
   ~/.agents/venv/bin/python lib/portfolio_imagegen.py \
     --page 'https://gileskayo.me/ai-projects/marvin/' \
     --widths 860,1440 \
     --output ~/.claude/outbox/marvin-screenshots/
   ```

### On this worktree

6. **Verify no deploy/ push happened** (portfolio deployments are manual, never automatic):
   ```bash
   cd ~/portfolio-dev
   git status
   # Verify no deploy/ changes in unpushed commits
   if git diff --name-only origin/main..HEAD | grep -q deploy/; then
     echo "ERROR: deploy/ changes detected in unpushed commits"
     exit 1
   fi
   ```
   `git status` should be clean. The diff check ensures no deploy/ paths in unpushed commits.

## Verification Tests

All 11 verification tests from the plan:

1. **Claim-traceability worksheet** ✓ — `docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md`
2. **Privacy scan** ✓ — no private names, emails, paths, hostnames
3. **Content evaluator, zero findings** — run `lib/portfolio_content.py --json` after authoring
4. **Layout evaluator, zero findings** — run `lib/portfolio_eval.py` after authoring
5. **860px and 1440px screenshots** — capture with `portfolio_imagegen.py`
6. **Recovery-path check** — `--plan` and `--rollback` work
7. **Dependency-failure handling** — each tool reports success exit code, not just "printed something"
8. **Stale-mount check** — verify dev site mounts to `~/portfolio-dev/wordpress/html`, not local copy
9. **Single-writer check** — no other session has uncommitted diff in portfolio repo
10. **Oversized-asset check** — verify screenshots compress well and have lazy-load markup
11. **No-production-push guard** ✓ — confirmed `deploy/` stays clean (Gil's manual step)

## Rollback Plan

If anything goes wrong during authoring:

```bash
~/.agents/venv/bin/python lib/portfolio_longform.py \
  'https://gileskayo.me/ai-projects/marvin/' \
  --rollback
```

This restores the page to its state before the authoring run. The backup is saved to:
`~/.claude/outbox/migrations/marvin/before-rollback-<timestamp>.json`

## Sources & Evidence

All claims in the content are sourced to:

- **Recent PRs merged:** 2026-11-07 to 2026-11-24 (via `gh pr list --state merged`)
- **ADRs 0039–0046:** MARVIN Mobile architecture decisions (Accepted/Proposed status)
- **ADR 0075:** Voice endpoint (Proposed, ticket #670 still open)
- **PR #1413:** Multi-Mac peer care (merged 2026-11-24)
- **PR #1407, #1410, #1412:** Mail sorting (merged 2026-11-07–11-24)
- **PR #1408:** Local model consolidation (merged 2026-11-24, Oct 21 work)
- **VERSION:** Current 0.86.1
- **Skills count:** 34 SKILL.md files verified
- **README.md, CONTEXT.md:** Pipeline and system architecture
- **CHANGELOG.md:** Recent shipped features

## If Stuck

- Dev site not running? Check `docker ps` for the container.
- WordPress credentials? They're in `~/.env` on the development machine.
- Screenshots too large? Check `portfolio_imagegen.py` for compression flags.
- Content won't author? The page might not be a valid short-page template; check `portfolio_longform.py --plan` output for details.

## Next Steps After Deployment

1. Review the page on dev site at `https://gileskayo.me/ai-projects/marvin/`
2. Take screenshots at 860px and 1440px for the final visual check
3. Run privacy pass on screenshots (no unblurred sensitive info)
4. When ready for production: manual push to `deploy/` and FTP deploy per the portfolio's normal flow

## Notes

- This content reflects the system state as of **2026-11-25**
- All "in design" features (MARVIN Mobile, Voice) are honestly marked as such; no overclaiming
- The content is written in Gil's portfolio voice: direct, confident, proof-focused, no hedging
- No private names, emails, paths, or hostnames in the content
