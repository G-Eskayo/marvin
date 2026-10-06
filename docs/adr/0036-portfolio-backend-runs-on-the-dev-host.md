# 0036. The Portfolio tab's backend runs on the dev host; other machines call it

Date: 2026-10-06. Status: accepted.

## Context

The portfolio dev site runs on one machine at a time (portfolio repo ADR 0003), currently the mac-mini. The Portfolio
tab's backend (`dashboard/electron/main/portfolio.js`) assumes it runs on that same machine: it shells out to scripts that
`docker exec` wp-cli in the dev site's containers, writes into the dev site's files (`~/portfolio-dev/wordpress/html`),
and keeps its results (evaluation, generated images, inventory) in `~/.claude/portfolio/`, which code-sync deliberately
does not sync. On the laptop the tab therefore half-works: actions fail (no Docker), file writes land in a stale local
copy, and the result panels are empty.

Rejected:
- **Route only wp-cli over ssh.** Leaves the file writes and the unsynced results broken.
- **Mirror both ways** (wp-cli over ssh plus rsync of files and results). Two copies to keep in step, and a second sync
  channel beside code-sync.
- **Edit only on the mac-mini.** Works, but Gil works from the laptop.

## Decision

Run the Portfolio backend only where the dev site is. The webhook server (`dashboard/webhook-server`, already running on
the primary host per ADR 0032) also serves `POST /portfolio/<method>` with body `{ "args": [...] }`. It calls the same
`createPortfolio()` object and returns `{ ok: true, result }` or `{ ok: false, error }`. Only the backend's own method
names are accepted.

The dashboard decides per machine. When it is the dev host it calls the backend in-process, as before. Otherwise its
`portfolio:*` IPC handlers call a proxy with the same method names that POSTs to the dev host. By default the dev host is
the primary host (ADR 0032's `resolveServiceDefaults`), or `MARVIN_PORTFOLIO_HOST` when the dev site is moved. The client
uses a plain `http.request` with an explicit timeout, because `fetch` gives up after 300s waiting for headers and
evaluation/add-project runs take up to 15 minutes.

Component previews still load the dev site's stylesheets from `http://localhost:8080` in the renderer. On a non-dev-host
machine, `com.marvin.portfolio-dev-tunnel` (a launchd ssh forward, laptop only) makes that URL reach the dev host.

## Consequences

- Every tab feature works from any machine with no per-function remote code, and there is still one copy of the dev
  site and of its results.
- The dev host must be up, with its webhook server running, for the tab to work elsewhere. It already has to be up for
  approvals, so this adds no new dependency.
- **Known gap, inherited:** the webhook server listens unauthenticated on all interfaces, as `/approve` already does.
  The new endpoints write only to the dev site, MARVIN's result directories and the portfolio repo's working tree
  (`templates/`, plus the manifest when images are applied). They never commit, push or touch production, so this
  widens nothing beyond the dev site. Binding to Tailscale or adding a shared token should cover
  both.
- Moving the dev site to the laptop means setting `MARVIN_PORTFOLIO_HOST` (or moving the primary host) and unloading the
  tunnel.
