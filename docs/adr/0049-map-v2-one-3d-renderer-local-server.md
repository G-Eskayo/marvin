# 0049 — Map v2: one 3D map, two layers, served from its own localhost server

## Status

Accepted (2026-10-06).

## Context

The brain-map (`brain-map/`) draws the system tree in 3D on the desktop wallpaper (DesktopLive). It had overlapping labels, clipped
nodes, nothing built since July, a live feed that fails under `file://`, and an open bug (#136) where the wallpaper goes frozen, black
or wrongly sized. Separately, graphify's code graph (`graphify-out/graph.json`) holds MARVIN's real files, functions and call edges but
nothing shows it. Gil wanted the two mixed: an overview you can open into the code behind it, live with what MARVIN is doing, on the
wallpaper, in the dashboard and on the website.

Alternatives considered:

- **A force-graph library (3d-force-graph, force-graph, d3-force).** Rejected: they run layout and drawing on `requestAnimationFrame`,
  which WebKit suspends for desktop-level windows. The wallpaper is driven by a native 24 fps timer calling `window.renderFrame()`
  instead (the same bug class hit twice on 2026-07-17); a library would freeze there unless forked.
- **A 2D code layer under a 3D overview.** Proposed for label readability; Gil chose 3D throughout so opening a node feels like zooming
  into the same space.
- **Opening into a separate code scene, or several nodes at once.** Rejected: a separate scene reads as leaving the map; several open
  clusters collide. One node opens in place.
- **Serving from the dashboard webhook server (port 7878).** Rejected: it takes approvals and portfolio writes and is reachable from
  outside (n8n, tunnel). Live activity must not leave the machine.

## Decision

One renderer, the existing hand-built 3D scene, extended with a **code layer**. A system node opens in place: its owned code (by path)
appears as a cluster around it, grouped by graphify community, shared code it calls as faded borrowed nodes, tests hidden by default.

- **Layout is computed ahead of time** by the generator for both layers, the same every run. The browser runs no physics.
- **Labels are chosen every frame** by priority (open node, its files, groups, skills, functions), drawn only when their screen box is
  free and they aren't hidden behind other nodes. Function labels need hover or a close camera.
- **A dedicated map server**, a launchd job that restarts on failure, bound to `127.0.0.1` only, serves the page, the tree and the code
  data, and streams live events over SSE. It reads the sources itself: skill calls and files touched (MARVIN's code and project repos),
  job events, pipeline stage changes. Machine health and online/offline are states, not pulses.
- **Three surfaces, one page**: the wallpaper (system layer, live, not clickable), the dashboard map tab (both layers, live,
  clickable), the website snapshot (see [[0050]]). The host keeps driving frames through `renderFrame(t)`.
- **DesktopLive becomes self-healing and logs everything** (#136): it logs each draw, wake, display change and crash with its reason;
  rebuilds its windows on wake, login and display changes; reloads when WebKit's content process dies; shows a "map server down" frame
  and retries when the server is unreachable; and runs a liveness check that the page is really drawing. The daily 4 a.m. kill
  (`com.marvin.desktoplive-restart`) is a workaround that never reached the Mac mini, and it goes away once the liveness check exists.

## Consequences

- 3D code clusters (up to ~300 nodes for the largest areas) mean labels are always partly hidden; the no-overlap test checks the labels
  actually drawn, at several camera angles and widths, not that every label is visible.
- The wallpaper now depends on a second process. The fallback frame and the liveness check exist so that dependency fails loudly,
  not as a blank desktop.
- Ownership by path means a skill with no folder (or code living somewhere unexpected) opens empty; that is visible, not hidden.
- The `MARVIN` heartbeat in `activity.jsonl` is replaced by file-touched events; anything else reading that heartbeat needs checking.
