# Plan: portfolio storytelling and MARVIN map v2 (2026-10-06)

Gil's direction, 2026-10-06: the pages read as AI-written and undersell the work. Copy should sell (story first, then proof, so a lay reader gets the gist and a technical reader gets depth); see the writing-style skill's "Portfolio register". Everything below happens on the dev site or on branches. Nothing goes to production or to a public repo without Gil's go-ahead.

## 0. Writes keep their HTML (do first)

wp-cli runs with no user, so WordPress's HTML filter (kses) strips tags it doesn't allow. That is how SkineeDipping lost its video `<source>` (fixed on dev 2026-10-06 by using `<video src>`).

- [x] Every MARVIN tool that writes page content through wp-cli passes `--user=<admin>` (`portfolio_migrate`, `portfolio_add_project`, `portfolio_apply`, `portfolio_longform` and the one-off fix scripts).
- [x] A test fails if a writer omits it.
- [x] The evaluator flags any `<video>` with no playable source, and any `<img>` whose file is missing.

## 1. Clarity Captions page

Story: Gil is building this for his mom's birthday (25 October 2026). He decided to make it after watching her depend on paid captioning services that only work with a network connection and cost a lot. Goal: a free app that works offline. Competitors are never named.

- [x] Demo mode in the app: a launch flag plays a scripted two-person conversation through the real caption view (speaker colours, line breaks, scroll). Built on a branch with a PR in clarity-captions; it never ships enabled.
- [x] Screenshots from the iPhone 17 Pro simulator: captions mid-conversation, the appearance settings, landscape, first run.
- [x] Page rewritten in the new voice: the story, how it works for a lay reader, the architecture and the hard problems for a technical reader, an honest "what's left".

## 2. MARVIN page

- [ ] Story rewrite: the problem (Claude starts every session cold), what MARVIN does about it, what it does while Gil is away, then proof.
- [ ] Facts strip regenerated from the repo, never typed: skills, tests, merged PRs, closed issues, machines.
- [ ] Dashboard tour: one real screenshot per tab (Metrics, MR Review, Health, Docs, Activity, Portfolio), with a line on what each does.
- [ ] Charts: pipeline failures by cause over time, with fixes marked; bench cost against correctness (`bench/RESULTS.md`). Commit charts exclude `auto-sync` commits.
- [ ] "Built with MARVIN": links to the pages MARVIN built or runs (Resume Tailor, Paper Dive, the portfolio tooling, the Clarity and Killer Sudoku pipelines), and those pages link back.
- [ ] The card image and the page header are the same picture (a still frame of the map, until map v2 replaces both).

## 3. MARVIN map v2

Today's map (`brain-map/`) renders the system tree in 3D but has overlapping labels, a legend over the intro, clipped nodes, nothing built since July, and a live feed that fails under `file://`. Ticket #136's acceptance criteria are all open.

Direction (Gil): mix "fix the existing map" with "the code graph", all local, interactive with what the system is actually doing.

- **Two layers, one view.** The system layer (categories, skills, agents, infrastructure, machines, the dashboard, the pipeline, the projects MARVIN runs) is the overview. Clicking a node drills into its code from graphify's `graph.json`: that area's files, functions and call edges, clustered by graphify community. Vendor and generated files are filtered out.
- **Live, local.** Served from a local HTTP server, not `file://`. Pulses come from real events: skill calls (`activity.jsonl`), pipeline stage events, job events and machine health. No live data leaves the machine.
- **Same renderer everywhere.** The desktop wallpaper (DesktopLive), a dashboard tab, and an exported static snapshot for the website (interactive, not live, public repo data only).

Acceptance criteria:
- [ ] No overlapping labels and no clipped nodes at 1280–2560px widths (checked by a Playwright test).
- [ ] Every skill, recurring agent, machine and dashboard tab in the live system appears; the node list is generated, never hand-kept.
- [ ] Drill-down from any system node to its code and back.
- [ ] A live event appears as a pulse within 5 seconds.
- [ ] #136: the cause of the missing background is found and recorded; the agent logs why it did or didn't draw; it recovers after sleep, login and display changes; a script checks recovery.
- [ ] The website snapshot loads with no console errors and no local paths or private data in it.

Design questions to settle before building (grill-with-docs): renderer choice (keep the current Three.js scene or move to a 2D/3D force graph); how far the drill-down goes (files or functions); which events count as "live".

## 4. Paper Dive and Resume Tailor

- [ ] Push the staged repo updates (waiting on Gil: with or without the Fellows mention).
- [ ] Evidence: a citation-graph render from a real run; a side-by-side of a job posting and the resume it produced (Gil picks which).
- [ ] Short page rewrites in the new voice.

## 5. Health board: coverage and rework

Gil (2026-10-06): the Metrics rework is close to what he wants for evaluation and usage; Health should get the same treatment, and cover more of the system.

- [ ] Inventory what runs (launchd jobs, webhook server, pipeline, tunnels, sync, dev site, DesktopLive) against what Health watches; every gap gets a check.
- [ ] Rework the tab in the Metrics board's style.

## 6. Credentials panel and a self-hosted password manager

Gil (2026-10-06): Health should list every auth token and MCP server credential that needs renewing, warn before each expires, and let him paste in a new one. Secrets belong in a password manager, not the dashboard: the Bitwarden repos ingested into qa-knowledge (clients, server, sdk) are the starting point.

- [ ] Design pass first (security-sensitive): self-hosted server (Vaultwarden vs. Bitwarden's own stack), where it runs (mac-mini, Tailscale-only), how tools read secrets (Bitwarden CLI/SDK), and what the dashboard stores (names, owners and expiry dates only; never secret values).
- [ ] Inventory every credential in use (GitHub tokens, WordPress app password, MCP servers, ngrok, API keys) with its expiry and how it's renewed.
- [ ] The panel: expiry warnings, a renew link, and paste-a-new-token that writes to the vault.

## Bugs found along the way

- [ ] The portfolio pipeline hangs (blocked in `opendir`) when the webhook server launches it, but runs in about 3 minutes from a shell. Diagnose (launchd context vs. the iCloud-synced repo).
- [ ] code_sync's stash-and-pop conflicts on generated files (`bench/metrics/health-monitor.*`) and leaves the repo half-merged; treat generated files like the merge gate does.

## Order

0 → 1 → 2 → 3 → 4, then 5 and 6. Clarity comes first because it's the clearest story and its screenshots also feed MARVIN's "built with" section. The map is the largest item and gets its own design pass before code.
