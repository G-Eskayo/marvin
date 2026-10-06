# 0042 — The mobile backend is a standalone launchd service on the Mac Mini, Tailscale-only

## Status

Accepted (2026-10-05)

## Context

MARVIN Mobile's Dashboard surface needs the same data the Electron dashboard shows, and Chat/Voice
need a long-lived process that runs headless Claude Code sessions ([[0040]]) and sends push
([[0041]]). The Electron app only runs while it's open, and Gil sometimes has it open on the
laptop rather than the Mac Mini.

Checked 2026-10-05: of the dashboard's main-process modules, only `electron/main/index.js` (the
IPC wiring) imports Electron — every data module (`activity.js`, `health.js`, `boards.js`,
`mr_review.js`, …) is plain Node already.

Alternative: host the backend inside the Electron main process — less code, but the phone goes
dark whenever the desktop app isn't open on the Mac Mini.

## Decision

Run the mobile backend as its own launchd-managed Node service on the Mac Mini (per [[0032]]),
importing the dashboard's data modules directly, bound only to the Mac Mini's Tailscale address.
Same shape as the portfolio backend ([[0038]]).

## Consequences

- Phone works whenever the Mac Mini is up, independent of any desktop app window.
- Dashboard data has one implementation shared by two front-ends; no copy to drift.
- Data modules become a contract the mobile backend depends on — changes to them can now break
  the phone, so they need tests at that boundary.
- Any implicit Electron-provided context (app paths, env loaded at Electron start) must be
  supplied explicitly by the service.
- Mac Mini availability becomes a user-facing dependency (see the headless-outage theory in
  memory) — the app should degrade visibly, not silently, when the backend is unreachable.
