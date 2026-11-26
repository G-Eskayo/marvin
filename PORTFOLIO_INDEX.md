# MARVIN Portfolio Refresh (#840) — File Index

**Status:** Content ready; deployment pending

## Main Deliverable

📄 **`content/longform/marvin.json`** (THE CONTENT)
- Updated portfolio content for gileskayo.me/ai-projects/marvin/
- 7 sections: What it does, What shipped recently, How the pipeline works, How memory works, What's in design, What you get, Open source & private
- Written in your portfolio voice (direct, confident, proof-focused)
- Ready for `portfolio_longform.py --author`

## Documentation

📋 **`PORTFOLIO_REFRESH_HANDOFF.md`** (START HERE)
- Quick summary of what's ready and what you need to do
- Lists all 7 deployment steps (copy-paste ready)
- Includes rollback procedure if something breaks

📋 **`docs/design/pipeline-g-eskayo-marvin-840-deployment.md`**
- Exact deployment commands with detailed explanations
- What each step does and why
- How to verify success at each stage

📋 **`docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md`**
- Every factual claim in the content mapped to its source
- Verification that all claims are traceable to repo evidence
- Status of each major feature (shipped vs. in-design)

📋 **`docs/design/pipeline-g-eskayo-marvin-840-summary.md`**
- Full work summary: what was done and what remains
- Lists the 11 verification tests from the plan
- Notes on what files are uncommitted and why

📋 **`docs/design/pipeline-g-eskayo-marvin-840.md`**
- Original plan for this ticket
- 10-step implementation plan with 11 verification tests

## Quick Start

1. **Review the content:**
   ```bash
   cat content/longform/marvin.json
   ```
   Or read it in the JSON structure — 7 sections with HTML bodies.

2. **Understand what changed:**
   - New emphasis: Multi-Mac peer care, mail sorting, local models, merge gate
   - Honest status: Mobile and Voice in design, not shipped
   - Open source and private architecture

3. **Deploy when ready:**
   - See `PORTFOLIO_REFRESH_HANDOFF.md` for all 7 steps
   - Everything runs on the development machine
   - Deployment is optional until you visually approve

## What's Verified ✅

- JSON structure valid
- Privacy clean (no private names, emails, paths, hostnames)
- Voice matches your portfolio register
- All claims traceable to sources (repo PRs, ADRs, git logs)
- 34 skills confirmed accurate
- Multi-Mac and mail sorting are recent and shipped
- Mobile and Voice clearly marked "in design"

## What's Waiting for Deployment

After running the deployment steps on the development machine, these will be completed:
- Authoring to dev site (portfolio_longform.py)
- Running evaluators (portfolio_content.py, portfolio_eval.py)
- Capturing screenshots (portfolio_imagegen.py at 860px and 1440px)
- Final visual verification
- Confirm no production `deploy/` push
- Portfolio page updated on dev site

## If You Want to Know More

- **What MARVIN does:** See `content/longform/marvin.json` → "What it does"
- **What shipped recently:** See `content/longform/marvin.json` → "What shipped recently"
- **What's coming next:** See `content/longform/marvin.json` → "What's in design"
- **How to deploy:** See `PORTFOLIO_REFRESH_HANDOFF.md`
- **Full evidence:** See `docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md`

## Uncommitted Files

```
content/longform/marvin.json
docs/design/pipeline-g-eskayo-marvin-840.md
docs/design/pipeline-g-eskayo-marvin-840-tasks.md
docs/design/pipeline-g-eskayo-marvin-840-claims-worksheet.md
docs/design/pipeline-g-eskayo-marvin-840-deployment.md
docs/design/pipeline-g-eskayo-marvin-840-summary.md
PORTFOLIO_REFRESH_HANDOFF.md (this file + content = all deliverables)
PORTFOLIO_INDEX.md (this file)
```

Stay uncommitted until you've reviewed and approved. Pipeline handles commit/push after deployment.

---

**Next step:** Read `PORTFOLIO_REFRESH_HANDOFF.md` for a 2-minute overview of what to do next.
