# Portfolio Repo Changes — What Will Uncommit When Execution Resumes

**Location:** ~/Developer/portfolio-website-updater  
**Trigger:** When steps 3–12 of the plan execute (after Decisions confirmed)

---

## Files That Will Change

### 1. `content/longform/marvin.json` (PRIMARY UPDATE)
**What:** The long-form content JSON for the MARVIN portfolio page

**Changes made per Decision choices:**
- Update "The dashboard" section: 7 tabs now (add Workshop mention, remove old "six tabs" claim)
- Add brief section/mention for MARVIN Mobile (in-progress)
- Add brief section/mention for MARVIN Voice (in-progress)
- Update all `data-fact` values: skills, tests, prs_merged, adrs, machines, counted_on
- Recount facts from GitHub/pytest at authoring time
- Verify pipeline PR chart, failure-causes chart, bench table (regenerate if stale)
- Change machine count from "2 Macs" to "3 machines" (mac-mini-2012 operational)

**Format:** JSON with structure like:
```json
{
  "title": "MARVIN",
  "sections": [
    {
      "heading": "The dashboard",
      "body": "... [updated with 7 tabs, Workshop added] ..."
    },
    {
      "heading": "On multiple Macs",
      "body": "... [updated: 3 machines including operational Kali box] ..."
    },
    {
      "heading": "... [new or updated sections for Mobile/Voice] ...",
      "body": "... [brief, honest descriptions] ..."
    }
  ],
  "data_facts": {
    "skills": "33",
    "tests": "7,600+",
    "prs_merged": "299",
    "adrs": "80+",
    "machines": "3",
    "counted_on": "2026-11-25"
  }
}
```

### 2. Dashboard Screenshots (MULTIPLE NEW FILES)
**What:** Fresh Playwright-captured screenshots of each dashboard tab

**Files (naming pattern `dashboard-{tab-slug}.jpg`):**
- `dashboard-metrics.jpg` (or existing filename pattern)
- `dashboard-workshop.jpg` ← NEW (Workshop tab just added, definitely needs fresh)
- `dashboard-mr-review.jpg`
- `dashboard-health.jpg`
- `dashboard-docs.jpg`
- `dashboard-activity.jpg`
- `dashboard-portfolio.jpg`

**Characteristics:**
- Captured via Playwright `_electron` on current dashboard app
- Run through privacy blur pass (remove/blur: tokens, emails, private projects)
- Visually verified for no overflow, proper rendering
- Timestamp: this week (≤ 7 days from authoring, per staleness test)
- Both @1440px and @860px widths captured per Decision 1

### 3. SVG Diagrams (CONDITIONAL)
**Paths:** `diagrams/context.svg`, `diagrams/pipeline.svg`, `diagrams/system.svg`

**Decision:** Regenerate only if architecture changed
- If no changes: reuse existing SVGs (mermaid theme matches)
- If changes detected: regenerate via `portfolio_diagrams.py`

**Likely impact:** Probably no changes needed (architecture stable), so these may remain as-is.

---

## Workflow When Resuming Execution

**Checklist order:**
1. `git log` portfolio repo for concurrent edits (Test 10: Concurrent-editor test)
2. Run `portfolio_longform.py marvin --plan` to verify page structure (Test 9: Rollback-safety)
3. Edit `content/longform/marvin.json` (Steps 4–5 of plan)
4. Take fresh screenshots + privacy pass (Step 4 of plan)
5. Update diagrams if needed (Step 6 of plan)
6. Run `portfolio_longform.py marvin --author content/longform/marvin.json` (Step 8)
7. Run `portfolio_sync_dev.py` (Step 9)
8. Run evaluator + 860px verification (Steps 10–11)
9. Final privacy scan on all images (Step 11)
10. Uncommit state: `git status` shows changes to marvin.json + new screenshots

---

## Risk Checklist (Mitigation)

| Risk | Mitigation | Test # |
|------|-----------|--------|
| Concurrent edits overwrite another session's work | `git log` before writing | 10 |
| Stale screenshots passed as current | Capture this week only | 5 |
| Unverifiable claims slip in | One-line source for every fact | 1 |
| Old numbers on the page (the whole reason for this ticket) | Recount from GitHub/pytest at build time | 6 |
| Privacy leak: tokens/emails/private names in screenshots | Blur pass + visual review | 4 |
| Docker down, dev site stale | Check dev-up.sh ran, Docker Desktop active | 11 |
| Narrow layout broken on 860px (Gil's review width) | Manual screenshot 860px per Decision 1 | 3 |

---

## Estimates (When Work Resumes)

| Step | Effort | Time |
|------|--------|------|
| 3: Dev-site check | Checks only | 2 min |
| 4: Screenshot retake | Playwright run + privacy pass | 10 min |
| 5: Rewrite JSON + verify numbers | Content edit + GitHub calls | 20 min |
| 6–7: Diagram + writing review | Review existing + read against GUIDE.md | 10 min |
| 8–9: Authoring + eval | portfolio_longform.py + sync_dev.py | 10 min |
| 10–11: 860px + privacy | Manual screenshot + final scan | 5 min |
| 12: Report | Write report to Gil | 5 min |
| **Total** | | **~62 min** |

---

## What Gil Will Review

**Uncommitted in portfolio repo after Step 11:**
- `content/longform/marvin.json` — Edited, fact-updated, Mobile/Voice added
- `dashboard-*.jpg` — 7 new screenshots (privacy-cleared)
- Possibly regenerated `diagrams/*.svg` (if architecture changed)

**Before deploying to production:**
- Verify screenshots in both @1440px and @860px widths
- Spot-check facts against the GitHub live state
- Confirm Dashboard, Mobile, Voice descriptions read correctly
- Run `portfolio_sync_dev.py` evaluation shows "complete" and no findings

Then: Gil manually deploys to production (auto-deploy not configured for this).

---

## For the Record

This is what *will* be uncommitted once execution resumes and completes through Step 11 (Report). The plan then stops at reporting to Gil (Step 12); deployment is his manual step.

**Current status:** Waiting at Step 2 (Decisions).
