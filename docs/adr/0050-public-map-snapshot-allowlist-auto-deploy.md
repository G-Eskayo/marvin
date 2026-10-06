# 0050 — The public map snapshot: allowlisted, private projects named but locked, deployed automatically

## Status

Accepted (2026-10-06).

## Context

Map v2 ([[0049]]) replaces the MARVIN portfolio page's still image (hero and card) with an interactive copy of the map. The local map
is built from the working copy, which holds untracked files, local paths, machine hostnames and Tailscale addresses, and MARVIN runs
private projects (`finance-os`, `portfolio-website-updater`). A blocklist (strip what looks private) fails open: anything nobody
thought of leaks. Leaving private projects off entirely hides the most honest thing the map can say about the work. A hand-refreshed
export goes stale, and with project names on show a stale snapshot is visibly wrong.

## Decision

- **Allowlist, not blocklist.** The code layer includes only files tracked in the public `G-Eskayo/marvin` repo at the commit being
  exported. Machines appear by kind ("Mac mini"), never by hostname or address. No live events, no health.
- **Private projects are locked nodes**: shown by name, never openable, no code, no events.
- **An export test blocks the deploy** if the output contains `/Users/`, an IP address, a private repo's code, an email address or a
  token pattern. A blocked deploy keeps the previous snapshot and raises a health warning.
- **Automatic rebuild**: nightly, and on any `marvin` commit that changes the system tree; the project list comes from the project
  catalog. It deploys through the portfolio's `deploy/` path only when the export changed and the test passed. No approval step.

## Consequences

- Project names (including private ones) become public the night they enter the catalog. Gil chose this on purpose; renaming or
  removing a project from the catalog is the way to keep one off the site.
- Correctness now rests on the catalog and the generator updating themselves. A stale or wrong catalog shows up on the public site.
- The still image stays as a fallback for clients without WebGL and for the page card.
