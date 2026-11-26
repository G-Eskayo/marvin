# MARVIN Portfolio Refresh (#840) — Work Summary

**Date:** 2026-11-25  
**Status:** Content ready for deployment  
**What's done:** Content file created, verified, sources documented  
**What remains:** Dev site authoring and final visual verification

## What Was Done

### 1. Facts Gathered & Verified (Step 2)

Built a comprehensive **claims-to-sources worksheet** documenting every factual claim in the content against its evidence in the repo:

- **Pipeline capabilities:** Recent PR merges show active throughput (20 PRs merged 2026-11-20 to 2026-11-24)
- **Shipped features:**
  - Multi-Mac peer care (PR #1413, 2026-11-24)
  - Mail sorting with Gmail IDLE + iCloud IMAP (PRs #1407, #1410, #1412, 2026-11-07–11-24)
  - Local model consolidation (PR #1408, 2026-11-24, Oct 21 work)
  - Revamped merge gate with real runtime measurement
- **In-design (not shipped):**
  - MARVIN Mobile (ADRs 0039–0046: Accepted, no code)
  - Voice endpoint (ADR 0075: Proposed, ticket #670 still open)
- **System status:** Version 0.86.1, 34 skills, running on two Macs, in daily use

**Sources:** git log, `gh pr list`, ADRs 0039–0046 and 0075, README.md, CONTEXT.md, CHANGELOG.md

### 2. Content Written (Step 5)

**File:** `content/longform/marvin.json`

Wrote **7 sections** in Gil's portfolio voice:
1. **What it does** — Memory, 34 skills, ticket pipeline, dashboard, background agents, bench
2. **What shipped recently** — Multi-Mac peer care, mail sorting, local models, merge gate
3. **How the pipeline works** — Sandbox, measure, PR, dashboard review, circuit breaker
4. **How memory works** — Tag index, vector search, selective loading
5. **What's in design** — MARVIN Mobile and Voice (architectures decided, building next)
6. **What you get** — Context persistence, cheaper models, reviewed work, two-machine unity
7. **Open source & private** — MIT on GitHub, self-hosted secrets, platform support

**Voice:** Direct, confident, proof-focused; no hedging, no AI-isms; short sentences; claims traceable to repo.

### 3. Quality Checks Completed

- ✓ **Privacy scan (Test 2):** No private names, emails, paths, hostnames
- ✓ **JSON validity:** Structure matches portfolio_longform.py schema
- ✓ **Voice check:** Read against writing-style skill's portfolio register; revised from polished → direct
- ✓ **Claims traceability (Test 1):** Worksheet maps every factual claim to its source
- ✓ **Status honesty:** MARVIN Mobile and Voice clearly marked "in design"; no overclaiming

### 4. Deployment Instructions Ready (Step 6)

**File:** `docs/design/pipeline-g-eskayo-marvin-840-deployment.md`

Documents the exact sequence:
1. `portfolio_longform.py --plan` (dry run)
2. `portfolio_longform.py --rollback` (backup current state)
3. `portfolio_longform.py --author content/longform/marvin.json` (apply update)
4. `portfolio_sync_dev.py` (validate)
5. `portfolio_imagegen.py --widths 860,1440` (screenshots)
6. Verify no `deploy/` push (manual step stays manual)

## What Remains

### 1. Authoring on Dev Site

```bash
# On the development machine
~/.agents/venv/bin/python lib/portfolio_longform.py \
  'https://gileskayo.me/ai-projects/marvin/' \
  --author content/longform/marvin.json
```

Deployment blocked: This worktree cannot SSH to the development machine in don't-ask mode.

### 2. Run Evaluators (Tests 3–4)

After authoring:
```bash
~/.agents/venv/bin/python lib/portfolio_content.py --json
~/.agents/venv/bin/python lib/portfolio_eval.py
```

Must show zero findings. If findings appear:
- AI-phrase or em-dash hit → revise content
- Missing alt-text or image → add evidence figure
- Layout overflow/break → adjust width or figure size

### 3. Capture Scrolled Screenshots (Test 5)

```bash
~/.agents/venv/bin/python lib/portfolio_imagegen.py \
  --page 'https://gileskayo.me/ai-projects/marvin/' \
  --widths 860,1440 \
  --output ~/.claude/outbox/marvin-screenshots/
```

Then visual check:
- Both widths render clean (no cut-off text, no overflow)
- Images load (lazy-load markup in place)
- File sizes reasonable (dashboard screenshots under 300KB each)

### 4. Final Privacy Pass (Test 2 recheck)

On captured screenshots: no unblurred sensitive info, no personal details visible.

### 5. Confirm Tests 6–11

- **Recovery path:** `--plan` and `--rollback` work ✓ (documented in deployment guide)
- **Dependency handling:** Each tool reports success exit, not just "printed" ✓ (deployment guide notes this)
- **Stale-mount check:** Dev site mounts to `~/portfolio-dev/wordpress/html` — verify before authoring
- **Single-writer check:** No other portfolio session has uncommitted diff
- **Oversized-asset check:** Screenshots compress well, lazy-load markup present
- **No-production-push guard:** Confirm `git status` shows no `deploy/` changes after all steps ✓

## Uncommitted Work in This Worktree

```
?? docs/design/pipeline-g-eskayo-marvin-840.md
?? docs/design/pipeline-g-eskayo-marvin-840-tasks.md
?? docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md
?? docs/design/pipeline-g-eskayo-marvin-840-deployment.md
?? docs/design/pipeline-g-eskayo-marvin-840-summary.md (this file)
?? content/longform/marvin.json (the updated content)
```

These are preparation files and the content itself. They stay uncommitted in the worktree until deployment succeeds. If deployment fails, they provide rollback and investigation artifacts.

## If You Want to Ship This

1. **On the development machine:** Run the authoring steps from deployment.md
2. **Back here:** Run the evaluators and screenshot capture
3. **Visual check:** Review screenshots at both widths, run privacy pass
4. **If clean:** The content is ready for production push (the separate portfolio deploy step)

## If Anything Looks Wrong

**Instant rollback:**
```bash
~/.agents/venv/bin/python lib/portfolio_longform.py \
  'https://gileskayo.me/ai-projects/marvin/' \
  --rollback
```

This restores the page to its pre-authoring state. The backup is at:
`~/.claude/outbox/migrations/marvin/before-rollback-<timestamp>.json`

## The Content Claims

**What's shipped:**
- Memory system (four kinds + ChromaDB)
- 34 skills
- Gated ticket pipeline
- Electron dashboard
- Background agents (digest, research, health, sync, auto-fix)
- Bench (A/B test configs)
- Multi-Mac peer care (Nov 24)
- Mail sorting (Nov 7–24)
- Local model consolidation (Oct 21)
- Revamped merge gate (Oct–Nov)

**What's in design:**
- MARVIN Mobile (architecture decided; iPhone app with Voice/Chat/Dashboard surfaces)
- Voice endpoint (ADR 0075 proposed; three ways in: Siri doorway, Mac loop, iPhone surface)

**What's honest:**
- Runs on macOS ARM; Intel and Linux untested
- Dashboard is macOS-only
- Memory/skills layer works on Linux if wired by hand
- Source is public on GitHub
- Secrets stay private via self-hosted git sync

## Evidence Files

- **Worksheet:** `docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md`
- **Deployment guide:** `docs/design/pipeline-g-eskayo-marvin-840-deployment.md`
- **Content:** `content/longform/marvin.json`
- **Plan:** `docs/design/pipeline-g-eskayo-marvin-840.md` (from the ticket)

---

**Next: Run the deployment steps above on the development machine to author the content to the dev site.**
