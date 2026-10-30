# Health card per Mac: resets and recovery (marvin#847), mock-up

**Status: mock-up for approval (owner's answer `fix-log` on #769). The real dashboard is unchanged.**

Open `index.html` in Chrome straight from Finder, with `?scene=<id>&view=grid|detail`. Scenes: `today` (nothing set
up yet, which is the real state on 2026-10-30), `quiet`, `waiting`, `notice`, `helper`, `incident`, `needsyou`, `away`.
`node docs/design/847-health-card/shoot.mjs <outDir>` takes the screenshots used on the PR.

Every word on the cards comes from state the build already writes: the night's file
(`~/.claude/logs/nightly-reset/<device>.json`), the incident and last probe (`~/.agents/var/peer-care/<peer>.json`,
`.last.json`), and the `nightly-reset` / `peer-care-<peer>` runs in job_events. Building the card is a
`health_checks.py` check per Mac (`care:<device>`) plus the drill-down section, after the Decisions on the PR.
