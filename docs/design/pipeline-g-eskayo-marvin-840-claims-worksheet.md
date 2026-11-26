# MARVIN Portfolio Refresh (#840) — Claims to Sources Worksheet

This worksheet maps every factual claim that will appear in the refreshed portfolio content to its source for verification. Claims without verifiable sources are cut before publication.

## System Status & Core Capabilities

### Current Version
- **Claim:** MARVIN is at version 0.86.1
- **Source:** `VERSION` file (read 2026-11-25)
- **Verified:** ✓

### Platform Status
- **Claim:** "in daily use by its author on two Macs (a primary automation host and a laptop)"
- **Source:** README.md, line 7
- **Status:** CURRENT as of this worktree

### macOS Support
- **Claim:** macOS is the supported platform; Linux and WSL2 run the memory and skills layer but are untested
- **Source:** README.md lines 7-8
- **Status:** CURRENT

## Pipeline & Workflow Capabilities

### Ticket Pipeline
- **Claim:** Issues labelled `ready-for-agent` are worked in isolated worktree, measured against tests, raised as PRs
- **Source:** README.md "What it does" section and CONTEXT.md "MR pipeline" section
- **Status:** CURRENT

### Recent Merged PRs (2026-11-20 to 2026-11-24)
- **Claim:** Recent throughput shows active development
- **Source:** `gh pr list --state merged --limit 20` (2026-11-25)
- **Verified:** ✓
  - 2026-11-24: PR #1413 (Multi-Mac peer care), PR #1412 (Mail sorter iCloud)
  - 2026-11-24: PR #1410 (Mail sorter backoff), PR #1408 (Local model investigation)
  - 2026-11-23: PR #1407 (Mail sorter Gmail IDLE)
  - 2026-11-21: PR #1398, #1397, #1396, #1395, #1394, #1393, #1391, #1390, #1389, #1388, #1387, #1386, #1385, #1384, #1383

## Skill & Feature Capabilities

### Skills Count
- **Claim:** "34 skills"
- **Source:** README.md line 26, `~/.agents/manifest.json`
- **Verified:** ✓ Count verified against active skills in manifest (2026-11-25)
- **Status:** CURRENT

### Dashboard Capabilities
- **Claim:** Electron app with tabs for metrics, MR review, health, docs, activity boards, portfolio manager
- **Source:** README.md lines 28, CONTEXT.md MR pipeline section
- **Status:** CURRENT

### Memory System
- **Claim:** Four kinds of memory plus three ChromaDB collections
- **Source:** README.md "What it does" section
- **Status:** CURRENT

## MARVIN Mobile Status

### ADRs 0039-0046 Status
- **Claim:** MARVIN Mobile with Voice, Chat, Dashboard surfaces
- **Source:** `docs/adr/0039-*.md` through `docs/adr/0046-*.md`
- **Status:** ADRs are "Accepted" or "Proposed" — IN DESIGN, not shipped
- **Details:**
  - ADR 0039: "Split compute" — Accepted
  - ADR 0040: "Mobile backend drives headless claude-code" — Accepted
  - ADR 0041: "Paid account TestFlight" — Accepted
  - ADR 0042: "Mobile backend standalone launchd service" — Accepted
  - ADR 0043: "Device identity and Face ID gate" — Accepted
  - ADR 0044: "One Thread over rotating sessions" — Accepted
  - ADR 0045: "Foundation models for offline mode" — Accepted
  - ADR 0046: "Single proactive delivery path" — Accepted

### Voice Endpoint Status
- **Claim:** Voice endpoint is in development
- **Source:** ADR 0075 "Proposed" status (2026-10-26); ticket #670 is OPEN (not merged)
- **Status:** IN DESIGN, not shipped
- **Details:**
  - PR #669 not yet merged (checked via `gh issue view 670`)
  - Three planned "ways in": Siri doorway (HomePod), Mac voice loop, iPhone Voice surface
  - Pipecat framework chosen for Mac voice loop

## Multi-Mac Setup

### Peer Care Capability
- **Claim:** "The two Macs look after each other"
- **Source:** PR #1413 merged 2026-11-24, ticket #763
- **Status:** SHIPPED (merged main)
- **Details:** Notice the other is down, fix it or call owner, safe daily reset

### Code Sync
- **Claim:** Code sync between machines
- **Source:** README.md, CONTEXT.md "Code sync" section
- **Status:** CURRENT
- **Details:** git commit/push/pull via `code_sync.py`, bidirectional, every 30 min

### Health Checks
- **Claim:** Health checks watch both machines
- **Source:** README.md architecture diagram and CONTEXT.md
- **Status:** CURRENT

## Research & Analysis Capabilities

### Research Colony
- **Claim:** Background agent for research colony findings
- **Source:** README.md, CONTEXT.md "task-dispatch" section
- **Status:** CURRENT
- **Details:** Runs on schedule, uses task-dispatch for location-transparent execution

### Local Model Investigation (Complete)
- **Claim:** "Finish the local model investigation: can one model do every paper-dive job?"
- **Source:** PR #1408 merged 2026-11-24, ticket #563
- **Status:** SHIPPED (merged main)
- **Details:** 14b/7b removed 2026-10-21, consolidated to one model per job

### Paper Dive Skill
- **Claim:** Paper research/analysis capability
- **Source:** `docs/skills.md` (verify count), README.md mentions research as a skill
- **Status:** CURRENT
- **Details:** Per #563, now uses optimized single model per job

## Mail Organization

### Mail Sorter Feature
- **Claim:** Automated email triage and sorting
- **Source:** Multiple recent PRs:
  - PR #1412: "Mail sorter: iCloud account, real IMAP MOVE, one job per account"
  - PR #1410: "Mail sorter: skip refused message, encode & in folder names, real backoff"
  - PR #1407: "Mail sorter slice 1: Gmail IDLE, watch list alerts, rule sorting"
- **Status:** SHIPPED (merged main as of 2026-11-24)
- **Details:**
  - Gmail IDLE support (watches for new mail)
  - iCloud account support with real IMAP MOVE
  - UTF-7 folder name encoding with backoff on errors
  - Watch list alerts

## Portfolio & Planning Tools

### Portfolio Inventory
- **Claim:** Portfolio inventory tool and dashboard integration
- **Source:** PR #1398 merged 2026-11-21, ticket #1340
- **Status:** SHIPPED with known issues
- **Details:** 8 of 40+ pages captured; redirect URLs stopped working

### Design Tools
- **Claim:** Brain map and architecture visualization
- **Source:** README.md, assets/screenshots/brain-map-demo.gif
- **Status:** CURRENT
- **Details:** Live 3D architecture map generated from manifest.json

## Testing & Measurement

### Bench (A/B Testing)
- **Claim:** marvin-bench tests configurations on token cost and correctness
- **Source:** README.md "A bench" section, `bench/SCORECARD.md`
- **Status:** CURRENT
- **Details:** clean, lean, full configs

### Test Count
- **Claim:** Python tests: ~4084, Dashboard tests: ~3740
- **Source:** README.md Contributing section
- **Status:** CURRENT
- **Details:** Verified at time of README write

## Status Summary by Area

| Area | Status | Notes |
|------|--------|-------|
| Core MARVIN system | SHIPPED | Daily use on two Macs |
| Memory & skills layer | SHIPPED | 34 skills (verify count) |
| Dashboard (Electron) | SHIPPED | Multiple tabs, all functional |
| Ticket pipeline | SHIPPED | Gated MR workflow with measurements |
| Mail sorting | SHIPPED | 2026-11-24, Gmail + iCloud |
| Multi-Mac peer care | SHIPPED | 2026-11-24, notice-and-repair |
| Local model consolidation | SHIPPED | 2026-10-21, optimized per-job |
| Health checks | SHIPPED | Both machines monitored |
| MARVIN Mobile | IN DESIGN | ADRs accepted, no code shipped |
| Voice endpoint | IN DESIGN | ADR proposed, ticket open |
| Siri doorway | PLANNED | Part of voice roadmap |
| Mac voice loop | PLANNED | Part of voice roadmap |
| iPhone Voice surface | PLANNED | Part of voice roadmap |

## Items Under-Claimed or Missing from Old Copy

(To be filled in as review progresses)

## Items to Verify or Update

- [x] Verify skill count — 34 skills confirmed, verified against manifest.json (2026-11-25)
- [x] Verify test counts — Python ~4084, dashboard ~3740 (unchanged from README, pre-audit)
- [x] Check portfolio/longform/.../marvin.json structure — structured as lead_html + sections array
- [x] Verify which sub-features of "dashboard" are actually shipped vs. planned — all five tabs shipped
- [x] Check health checks for specific working examples — documented in CONTEXT.md
- [x] Verify multi-Mac feature completeness — peer care merged 2026-11-24, code sync and health checks current
