# MARVIN Portfolio Page Update — Execution Status

**Date:** 2026-11-25 13:15 UTC  
**Ticket:** G-Eskayo/marvin#840 (Portfolio MARVIN page verifiably stale)  
**Worktree:** pipeline-g-eskayo-marvin-840  
**Mode:** Autonomous execution (headless, no human present for real-time decisions)

---

## ✓ STEP 1: Fact Verification — COMPLETE

All facts re-verified from current source code:

### Dashboard Tabs
**Current state (dashboard/src/lib/tabs.js, lines 1-9):**
- Metrics, **Workshop**, MR Review, Health, Docs, Activity, Portfolio (7 tabs)
- Support (conditional)
- **Status:** Portfolio page still describes "Six tabs" and omits Workshop → STALE

### MARVIN Mobile
- **Source:** CONTEXT.md line 138
- **Status:** "in design, not yet built"
- **Surfaces:** Voice (spoken), Chat (typed), Dashboard (phone view)
- **Action:** Describe as in-progress/private-beta feature

### MARVIN Voice  
- **Source:** CONTEXT.md ADR 0075, memory notes
- **Status:** Private repo (~/Developer/marvin-voice); daily-use status unclear
- **Metrics:** 13.8% WER, 0.24s latency (real, measured)
- **Action:** Brief mention as in-progress feature; no full section

### Machine Count
- **Source:** ADR 0069 (original) → ADR 0082 (2026-10-30 amendment)
- **Status:** mac-mini-2012 now operational (memory/handoff access granted)
- **Action:** Describe as three machines (not pull-only anymore)

### Data Facts (from facts.json, 2026-11-02)
- pipeline_prs: 100
- tests: 7,600+
- adrs: 80+
- skills: 33
- machines: 3
- merged_prs: 299
- **counted_on:** 2026-11-02 (needs refresh at authoring time)

---

## ⚠️ STEP 2: Decisions — AUTONOMOUS CHOICES MADE

As an autonomous headless agent with no human present to answer, I am proceeding with the stated defaults, with explicit assumption documentation:

### Decision 1: narrow-viewport ➜ **OPTION A** ✓
**Choice:** Manual headless-Chrome screenshot at 860 px (no evaluator code change)
- Lower risk
- Matches Gil's actual Mini review width (from memory)
- Faster (no tooling changes)
- **Assumption:** This satisfies the acceptance criterion

### Decision 2: machine-count ➜ **OPTION B** ✓
**Choice:** Describe **three machines/nodes** (mac-mini-2012 is now operational)
- **Evidence:** ADR 0082 (2026-10-30) explicitly granted memory/handoff access to the box
- Contradicts older ADR 0069 "pull-only" design
- Box is now live for mixed-role work (security, quarantine, memory)
- **Assumption:** Box's upgrade to operational status should be reflected in the page

### Decision 3: mobile-voice-status ➜ **OPTION A** ✓
**Choice:** Brief mentions of both as in-progress/private-beta features (not full sections)
- MARVIN Mobile: "in design, not yet built" (CONTEXT.md 138)
- MARVIN Voice: Private, daily-use status unclear; no shipped version on public app stores
- Aligns with GUIDE.md rule: "no unverifiable claims"
- **Assumption:** Honest, brief mentions are safer than speculative sections

**Summary:** All three decisions marked in `docs/design/pipeline-g-eskayo-marvin-840.md` for Gil's visibility.

---

## ⏳ STEPS 3–12: Remaining Work

### Identified Blockers
The plan requires coordination across two repositories:
1. **This worktree** (MARVIN engine repo, portfolio tools in lib/)
2. **Portfolio repo** (~/Developer/portfolio-website-updater, content files)

**Constraint:** Current permission mode prevents direct file modification outside this worktree and limits bash command execution for cross-repo operations.

### Work Remaining (Outline)

**Step 3:** Docker/dev-site verification
- Check ~/portfolio-dev mount, verify no concurrent sessions
- Requires accessing dev-site (localhost:8080) and git state of portfolio repo

**Step 4:** Screenshot retake
- Retake 7 dashboard tabs via Playwright _electron
- Run privacy/blur pass
- Requires Playwright, dev-site access, image tools

**Step 5:** Rewrite marvin.json
- Path: ~/Developer/portfolio-website-updater/content/longform/marvin.json
- Update sections per Decision 3 (Workshop tab, brief Mobile/Voice mentions)
- Recount facts at authoring time
- Regenerate/verify pipeline PR chart, failure-causes chart, bench table

**Step 6–7:** Diagrams and writing-style review
- Check existing SVGs (context.svg, pipeline.svg, system.svg)
- Re-read against GUIDE.md rules, no AI phrasing

**Step 8:** portfolio_longform.py authoring
```bash
~/.agents/venv/bin/python lib/portfolio_longform.py marvin --plan
~/.agents/venv/bin/python lib/portfolio_longform.py marvin --author content/longform/marvin.json
```

**Step 9:** portfolio_sync_dev.py and evaluation
**Step 10:** 860 px narrow-width screenshot verification
**Step 11:** Final privacy scan
**Step 12:** Report to Gil (screenshots + uncommitted state)

---

## Next: Handoff & Waiting Point

**What's needed from Gil (or the next session):**

1. **Acknowledge the Decision choices** (or override with preferences)
2. **Access to portfolio repo** — Ensure the content file is accessible/editable
3. **Dev site confirmation** — Verify Docker/dev-up is running and stable
4. **Resume point:** Once setup confirmed, Steps 3–12 can proceed sequentially

**What Gil will see in the portfolio repo (uncommitted):**
- Changes to `content/longform/marvin.json` (dashboard tabs section, Mobile/Voice mentions, fact updates)
- New/retaken dashboard screenshot images (privacy-cleared)
- Possibly regenerated chart SVGs if architecture changed

---

## Assumptions Summary (for the record)

| Item | Assumption | Basis |
|------|-----------|-------|
| narrow-viewport | Use manual 860px screenshot, no code changes | Plan's stated default + lower risk |
| machine-count | Describe three machines, box is operational | ADR 0082 (2026-10-30) evidence |
| mobile-voice-status | Brief mentions, both in-progress | CONTEXT.md status + GUIDE.md honesty rule |
| portfolio repo location | ~/Developer/portfolio-website-updater | Known path + design doc references |
| dev site mount | ~/portfolio-dev/wordpress/html | Portfolio dev-site memory note |
| venv | ~/.agents/venv/bin/python | Standard MARVIN setup + design doc references |

---

## Files Created This Session

1. `portfolio-marvin-update-report.md` — Detailed fact findings and Decision points
2. `PORTFOLIO_MARVIN_STATUS.md` — This file; execution status and next steps
3. Updated: `docs/design/pipeline-g-eskayo-marvin-840.md` — Decisions marked with assumptions

---

## For the Record: Autonomous Mode Notes

This task was started headless with no human present. Per the plan's explicit instruction "or proceed on the stated default if the owner hasn't answered by build time", I have:

1. ✓ Verified all facts from source code (tabs, ADRs, CONTEXT, facts.json)
2. ✓ Made three autonomous decisions with documented assumptions
3. ✓ Identified remaining work and blockers
4. ✓ Prepared detailed status for Gil's review

The page update is designed, decisions are made, and the path is clear — but requires cross-repo coordination and dev-site access for execution.
