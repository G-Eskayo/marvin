# The MARVIN map on the website, kept current — 2026-10-08

For #189. Decided with Gil 2026-10-08:

- **Auto-update:** the map snapshot publishes itself to production (standing permission for the map only, ADR 0056).
  Everything else on the site stays Gil's manual promotion.
- **Placement:** the MARVIN page hero stays a still image that matches the project card. The page gets its own
  section with the interactive map.
- **On the website:** only the 3D map on a transparent background, no header, legend, footer or mode switch.
  Drag to rotate, hover for each node's plain-words line.
- **Desktop backgrounds** (DesktopLive) keep the full local map and pick up the new connections and hover lines.

## Pieces

1. **Embed mode.** `?embed=1` on the same snapshot page sets an `EMBED` flag
   that hides every panel and makes the page background transparent. The full `index.html` stays for direct visits.
2. **Publisher** (`brain-map/publish_map.py`). After a dev deploy passes the privacy scan, copy `snapshot/` into
   `deploy/marvin-map/` of a dedicated sparse checkout of the portfolio repo (`~/Developer/portfolio-map-publisher`,
   only that folder checked out), commit, and push to `main`. The GitHub action uploads `deploy/` to
   `/gileskayo.me/wp-content/`, so production serves `/wp-content/marvin-map/`, the dev site's path.
   Guards: refuses when anything outside `deploy/marvin-map/` would change; no commit when nothing changed; never
   touches Gil's working checkout.
3. **Schedule.** Install `com.marvin.snapshot-deploy-nightly` and `-reactive` on the mini with publishing on; add both
   to `JOB_PLACEMENT` (mini) so the Health tab watches them.
4. **MARVIN page section** "Explore the map" in `content/longform/marvin.json`: an iframe of
   `/wp-content/marvin-map/?embed=1`, with the hero image as a still fallback. Authored on the dev site; production
   gets it when Gil promotes the page.
5. **Hero = card.** The page hero and the card thumbnail come from the same picture.
6. **Desktop backgrounds.** After the PR merges, regenerate on both Macs and confirm DesktopLive shows the new map.

## Tasks

- [x] 1 embed page (`?embed=1`), with a browser test (transparent, no panels, hover works, page keeps the wheel)
- [x] 2 publisher `publish_map.py`, 6 tests on a real git origin; wired into `deploy_snapshot.py` (3 tests)
- [ ] 3 launchd jobs + JOB_PLACEMENT: plists fixed (working dir, PATH, publish on), mini-only installer, JOB_PLACEMENT done; **install after the PR merges** (the jobs run the main checkout)
- [ ] 4 MARVIN page section on dev: **blocked** 2026-10-08, the mini's iCloud copy of the portfolio repo fails reads (`Interrupted system call`); needs #192
- [x] 5 hero matches card: `render_map_images.py` cuts both from one frame (written to the mini's portfolio copy, uncommitted, promoted by Gil)
- [ ] 6 desktop backgrounds regenerated, checked
