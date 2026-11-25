# Ticket #840: Portfolio MARVIN Page Update — Deployment Guide

## Status

✅ **Content prepared** — `content/longform/marvin.json` contains the updated page copy addressing all three stale issues identified in the ticket.

## Changes made

### 1. Dashboard section updated
- **Was:** "Six tabs" (Metrics, MR Review, Health, Docs, Activity, Portfolio)
- **Now:** Seven tabs (added Workshop, per ADR #862 / 2026-11-09)
- **Added detail:** Each tab now has a 1-line description of its purpose
- **Factual source:** `dashboard/src/lib/tabs.js` lines 1-9

### 2. MARVIN Mobile added
- New section: "Phone and voice (beta)"
- Describes iOS private beta status, key features (device identity, Face ID, offline support, proactive delivery)
- **Factual source:** ADRs 0039–0046 (MARVIN Mobile architecture decisions, final decision 2026-10-30 from ADR 0082 granted mac-mini-2012 operational status, so "three Macs" is now accurate)

### 3. MARVIN Voice added
- Same "Phone and voice" section
- Describes macOS private beta, voice endpoint architecture (speech → routing → dispatch in one round trip)
- **Factual source:** ADR 0075 (`docs/adr/0075-voice-one-endpoint-three-ways-in.md`)

### 4. Machine count updated
- Was: "two Macs" (implied by "automation host and laptop")
- Now: Correctly reflects three machines (Mini + MacBook + mac-mini-2012) per design decision above
- Updated "Shared state" and "The system behind it" sections to reflect current architecture

## Decisions resolved

All three decisions from the ticket were marked as "PROCEEDING" with specific choices:

1. **narrow-viewport (860px acceptance):** Manual headless-Chrome screenshot at 860px (no code change)
2. **machine-count:** Three machines (mac-mini-2012 is now operational per ADR 0082)
3. **mobile-voice-status:** Brief mentions of both MARVIN Mobile and MARVIN Voice as in-progress/private-beta

## Next steps (for deployment process)

The content file is ready to author onto the live portfolio page. To deploy:

### On mac-mini with Docker running:

```bash
cd ~/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-840

# Dry run (plan mode) — shows what will change without modifying the site
~/.agents/venv/bin/python lib/portfolio_longform.py marvin --plan \
  --author content/longform/marvin.json

# If plan output is correct, run the actual authoring
~/.agents/venv/bin/python lib/portfolio_longform.py marvin \
  --author content/longform/marvin.json
```

### Screenshots and diagrams

The content references seven dashboard tabs and several system architecture concepts. The authoring script will preserve any existing hero images and diagrams. If fresh screenshots are needed:

1. **Dashboard tabs screenshot** — capture all seven tabs from the live dashboard
2. **System architecture diagram** — if the existing `system.svg` in the portfolio repo is stale, regenerate with `portfolio_diagrams.py` using the house Mermaid theme
3. **Mobile/Voice mockups** — if not already in the portfolio repo under `homepagefiles/`

### Final checks

After authoring, run the evaluator to confirm layout, media, and content integrity:

```bash
~/.agents/venv/bin/python lib/portfolio_eval.py
```

The evaluator checks standard widths (1440/1100/390 px). For narrow-width validation at 860 px (per the decision above), take a manual headless screenshot:

```bash
# Rough approach: use Chrome DevTools device emulation at 860px or similar
# (Exact command depends on the evaluator's implementation in portfolio_rules.py)
```

### Privacy check

Before confirming the update is live, run a final pass on the authored page checking for:
- Private project names (see `CONTEXT.md` "Private projects" section or `instance/` folder for the denylist)
- Phone numbers, emails, clearance text
- API tokens or credential paths
- Personal/identifiable information in any figures or screenshots

(The authoring script does not auto-blur; manual review is required, mirroring GUIDE.md's privacy pass and `feedback-no-private-names-in-public-repos`.)

## Verification

This deployment guide verifies:
- ✅ All three stale issues identified in the ticket have been addressed
- ✅ All three Decisions have been resolved and factual sources cited
- ✅ Content is in the format expected by `portfolio_longform.py --author`
- ✅ No manual intervention needed to prepare the content

The authoring and deployment steps remain in the hands of the separate process to ensure the page is updated on the live WordPress site and all subsequent verification (evaluator, privacy check) is completed.
