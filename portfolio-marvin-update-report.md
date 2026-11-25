# MARVIN Portfolio Page Update — Findings & Decision Points

## Status: Ready to Execute — Three Decisions for Gil

**Current date:** 2026-11-25  
**Last facts.json:** 2026-11-02  
**Plan created:** This worktree (pipeline-g-eskayo-marvin-840)

---

## ✓ Fact Verification Complete

### Dashboard Tabs (Verified)
Current dashboard in `dashboard/src/lib/tabs.js`:
- **Metrics** (line 2)
- **Workshop** (line 3, added per ADR 0080, #862)
- **MR Review** (line 4)
- **Health** (line 5)
- **Docs** (line 6)
- **Activity** (line 7)
- **Portfolio** (line 8)
- **Support** (conditional, line 11+)

**Status:** 7 tabs main + Support conditional. Current portfolio page still describes "Six tabs" and omits Workshop — needs update.

### MARVIN Mobile Status (Verified)
From `CONTEXT.md` line 138: **"in design, not yet built"**
- One app (not several) — supersedes July's separate "voice client" idea
- Three surfaces: Voice, Chat, Dashboard
- No repo at ~/Developer/marvin-mobile currently accessible
- **Recommendation:** Describe as "in progress" / "private beta" (Decision 3)

### MARVIN Voice Status (Verified)
From CONTEXT.md ADR 0075:
- Voice endpoint: "one place spoken words reach MARVIN"
- Mac voice loop with local wake word ("Hey MARVIN")
- Siri doorway integration on iPhone/HomePod/Watch
- Memory note shows real metrics: 13.8% WER, 0.24s latency
- Repo: ~/Developer/marvin-voice (private, PAID add-on per memory)
- **Status unclear:** Whether this is in daily use by build time (need Decision 3)

### Machine Count (Verified)
Three machines confirmed:
1. **MacBook Pro** — laptop, development
2. **Mac Mini** — stationary, primary (the system running this)
3. **mac-mini-2012** — Kali Linux node, operational
   - From ADR 0069: "pull-only node" for security/network-tools + quarantine
   - From ADR 0082 (2026-10-30 amendment): box now has full Claude memory access
   - **Status:** Operational (not pull-only design anymore) — go with **Option B**

### Data Facts (from site/src/data/facts.json, dated 2026-11-02)
Current values to update if stale:
- **pipeline_prs**: 100 (81 on MARVIN, 19 on Seal Speak)
- **tests**: 7,600+ (7,674 exact: 4,640 Python + 3,034 dashboard)
- **adrs**: 80+ (82 exact)
- **skills**: 33
- **machines**: 3 ✓ (confirmed above)
- **merged_prs**: 299 (all merged on G-Eskayo/marvin since 2026-08-27)

**Next step:** Recount these live from GitHub/pytest when authoring (Step 5 of plan).

---

## ⚠️ Three Decisions Required

### Decision 1: narrow-viewport (860 px check)

**How should the "860 px" acceptance criterion be satisfied?**

- **A:** Run evaluator at current widths (1440/1100/390) + manual headless Chrome screenshot at 860 px. No code changes.
- **B:** Add 860 px to the evaluator's shared viewport list in `portfolio_rules.py` for site-wide coverage.

**Recommended:** **Option A** — Manual screenshot is lower-risk and doesn't require tooling changes.  
**Assumption if no answer by build time:** Use Option A.

---

### Decision 2: machine-count (How many machines?)

**How many machines does "several Macs" cover on the page?**

- **A:** Keep "two Macs" (Mini + MacBook) — mac-mini-2012 still pull-only/in-design.
- **B:** Describe "three machines" — mac-mini-2012 has progressed past pull-only design.

**Fact:** ADR 0082 (2026-10-30) added memory/handoff access to the box; it's now operational for mixed-role work, not pull-only.  
**Recommended:** **Option B** — Three machines/nodes (mac-mini-2012 is now live).  
**Assumption if no answer by build time:** Use Option B (evidence from ADR 0082).

---

### Decision 3: mobile-voice-status (How to phrase phone/voice?)

**How to phrase MARVIN Mobile and MARVIN Voice given they may not be shipped?**

- **A:** Describe both honestly as in-progress/private-beta features (brief mentions, not full sections).
- **B:** Give Voice a full section if in daily use by build time; keep Mobile to one honest line if unfinished.

**Fact:** 
- MARVIN Mobile: "in design, not yet built" (CONTEXT.md 138)
- MARVIN Voice: Private repo; real metrics exist (13.8% WER, 0.24s latency) but unclear if daily-use ready

**Recommended:** **Option A** — Brief mentions as in-progress/private-beta. Neither is currently shipped/released.  
**Assumption if no answer by build time:** Use Option A (conservative, honest, matches GUIDE.md's "no unverified claims").

---

## Next Steps (Plan Execution)

The plan has 12 steps:

1. ✓ **Fact verification** — COMPLETE (above)
2. ⏳ **Resolve Decisions** — Waiting for Gil's answers (or proceed with assumptions noted above)
3. ⏳ **Check dev-site Docker** — Verify ~/portfolio-dev is mounted, no concurrent sessions
4. ⏳ **Retake dashboard screenshots** — 7 tabs via Playwright `_electron`, privacy pass
5. ⏳ **Rewrite marvin.json** — Update facts, dashboard section, add/revise Mobile/Voice per Decision 3
6. ⏳ **Diagram check** — Regenerate or reuse existing SVGs per architecture changes
7. ⏳ **Writing-style review** — GUIDE.md rules, no AI phrasing
8. ⏳ **portfolio_longform.py** — Dry run then author
9. ⏳ **portfolio_sync_dev.py** — Sync, capture, parity, evaluate
10. ⏳ **Narrow-width check** — 860 px per Decision 1
11. ⏳ **Privacy scan** — Final check on screenshots/figures
12. ⏳ **Report to Gil** — Screenshots + decisions + uncommitted state

---

## Constraints & Notes

- This worktree contains the MARVIN engine and portfolio tools (portfolio_*.py in lib/)
- Actual content files (content/longform/marvin.json) are in ~/Developer/portfolio-website-updater
- Dev site runs on localhost:8080, mounts ~/portfolio-dev/wordpress/html (not repo copy)
- Portfolio tools can reference external repos; need ~/.agents/venv/bin/python to run
- No production deploy to run (Steps end at reporting to Gil; deploy is his manual step)

---

## Questions for Gil

1. **Decision 1 (narrow-viewport):** Use Option A (manual 860px screenshot) or Option B (add to evaluator)?
2. **Decision 2 (machine-count):** Keep "two Macs" or describe "three machines"?
3. **Decision 3 (mobile-voice-status):** Brief mentions of both in-progress (Option A) or fuller Voice section if daily-use (Option B)?

If no answer by build time: Proceeding with **Options A, B, A** (manual screenshot, three machines, brief mentions).
