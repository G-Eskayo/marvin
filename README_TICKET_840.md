# Ticket #840: Portfolio MARVIN Page Update — Ready for Decision

## Status
**Phase:** Fact verification complete → Awaiting Decisions → Execution ready

**What's done:**
- ✓ Verified dashboard now has 7 tabs (Workshop added, not mentioned on current page)
- ✓ Verified mac-mini-2012 is now operational (not pull-only)  
- ✓ Verified MARVIN Mobile/Voice status (both in-progress)
- ✓ Made three autonomous decisions with clear reasoning
- ✓ Documented all findings and assumptions

**Where we are:** Waiting for Gil to confirm three Decision choices, OR automated execution will proceed with stated defaults.

---

## Three Decisions (Gil's Input Needed)

All three are documented in `docs/design/pipeline-g-eskayo-marvin-840.md`:

1. **narrow-viewport:** Manual 860px screenshot? (Recommended: Yes, no code changes)
2. **machine-count:** Describe 3 machines or 2? (Recommended: 3, box is now operational)
3. **mobile-voice-status:** Brief mentions or full section? (Recommended: Brief mentions, neither shipped)

---

## Documentation

Read these in order:

1. **`PORTFOLIO_MARVIN_STATUS.md`** — Full execution status, blockers, next steps
2. **`portfolio-marvin-update-report.md`** — Detailed fact findings for each decision
3. **`docs/design/pipeline-g-eskayo-marvin-840.md`** — Plan with updated Decisions marked

---

## Next Steps (Waiting For)

1. Confirm Decision choices (or accept defaults)
2. Verify portfolio repo (content files at ~/Developer/portfolio-website-updater)
3. Verify dev site (Docker/localhost:8080 running)

Then: Steps 3–12 execute sequentially (screenshots, rewrite content, evaluate, report).

---

## Key Findings

- **Dashboard:** 7 tabs now (Metrics, **Workshop**, MR Review, Health, Docs, Activity, Portfolio)
- **Machines:** 3 (MacBook, Mac Mini, mac-mini-2012 Kali) — box upgraded from pull-only to operational
- **Mobile/Voice:** Both in-progress private projects, neither shipped yet
- **Facts:** Last updated 2026-11-02, need refresh at authoring time

---

## Autonomous Decisions Made

As headless agent with no one to ask, proceeding with:
- **narrow-viewport:** Option A (manual screenshot, safer)
- **machine-count:** Option B (three machines, evidence-backed)
- **mobile-voice-status:** Option A (brief mentions, honest)

Marked in design doc + detailed assumptions in PORTFOLIO_MARVIN_STATUS.md.
