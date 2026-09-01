# 0032 — mac-mini as primary automation host for ticket-pipeline

## Status

Accepted (2026-09-01)

## Context

`com.marvin.ticket-pipeline` and `com.marvin.dashboard-webhook` currently run only on
macbook-pro, a laptop that sleeps/closes between naps — the pipeline's continuity is only as
good as the laptop's uptime. Mac-mini already runs several other MARVIN launchd jobs
(`research-colony`, `daily-digest`, `cross-machine-merge`, `architecture-review`, `auto-fix`,
etc.) and stays up reliably (see G-Eskayo/marvin#109's PRD, #110's own acceptance criteria).

`task_dispatch.py`'s `dispatch()` already supports running its command on either machine —
locally (`_run_local`) or remotely over SSH (`_run_remote`), fully symmetric — and
`select_machine()` already picks whichever is live and not busy. Claiming (the
`claimed:<machine>` GitHub label, added right before dispatch — see `ticket_pipeline.py`'s own
docstring) is what actually prevents two dispatches of the *same* ticket, not which machine's
cron happens to fire. This means two independent copies of `ticket_pipeline.py`'s scanning
cron running on both machines simultaneously would not double-execute a ticket — it would just
be redundant, not unsafe.

`dashboard-webhook`, in contrast, is not a scanner — it's a synchronous receiver for a specific
dashboard GUI's own Approve/Deny clicks. Every dashboard GUI instance currently defaults its
webhook calls to `localhost`, so each running GUI needs its *own* local webhook-server today.
#112 (env-aware webhook URLs, part of #109's same PRD) is what will let a GUI point its calls
at mac-mini's webhook-server instead of its own machine's — until #112 ships, disabling
macbook-pro's `dashboard-webhook` would silently break Approve/Deny whenever the GUI happens to
be running there.

## Decision

**Asymmetric treatment of the two jobs, not "move everything and disable the rest":**

- **`ticket-pipeline`**: mac-mini becomes the sole active scanner. Install and load the job on
  mac-mini; once a real ticket completes end-to-end through it, `launchctl unload` (not delete)
  macbook-pro's copy. The `.plist` file stays on disk at
  `~/Library/LaunchAgents/com.marvin.ticket-pipeline.plist` on macbook-pro — unloaded, not
  removed — so re-enabling it later is one command, not a re-install.
- **`dashboard-webhook`**: install and load on mac-mini too (needed regardless, once #112 makes
  it reachable), but **leave macbook-pro's copy running** for now. Only unload macbook-pro's
  once #112 ships and the GUI's default target is confirmed pointing at mac-mini — disabling it
  earlier breaks a macbook-pro-hosted dashboard's Approve/Deny with no fallback.
- **`dashboard-launch`** (the Electron GUI itself): not relocated at all, per #109's own scoping
  — the GUI stays wherever Gil is sitting; only its data-source URLs (webhook, refresh) move,
  via #112.

**Manual-fallback procedure** (the "how to apply" #110 itself asked for): if mac-mini is
unavailable for an extended period, re-enable macbook-pro's ticket-pipeline with:
```
launchctl load ~/Library/LaunchAgents/com.marvin.ticket-pipeline.plist
```
No re-install needed — the file was never deleted, only unloaded.

## Consequences

- Until #112 ships, `dashboard-webhook` runs on both machines simultaneously — not a
  primary/secondary split yet for that job specifically, only for `ticket-pipeline`. This ADR's
  decision for `dashboard-webhook` is therefore a checkpoint, not the end state; #112 landing is
  what completes it.
- Redundant `ticket-pipeline` scanning was confirmed *safe* (claim-based coordination), not just
  tolerated — the decision to unload macbook-pro's copy is about avoiding pointless duplicate
  work and keeping one clear source of truth for "is the pipeline alive," not about correctness.
- If mac-mini's disk/venv/repo checkout ever drifts from macbook-pro's (e.g. `code_sync.py`
  fails silently), the pipeline could go quiet with no loud failure — this ADR doesn't add new
  monitoring for that; #109's Activity tab work is the intended visibility layer for exactly
  this failure mode.
