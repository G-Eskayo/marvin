1. `dashboard/electron/main/needs_you.js`: add `projectIdFor(ticket)` (imports `projectIdOf` from `../../src/lib/projects.js`) and attach `projectId` to each `rankNeedsYou` row.
2. `dashboard/test/needs_you.test.js`: add the four `projectId` cases (10–13 above).
3. `dashboard/electron/main/relations_service.js`: fix `overview()`'s `needsYou` tally to come from `rankNeedsYou(b.tickets)` grouped by `repo` (includes `needs-info`, matches list length).
4. `dashboard/test/relations_service.test.js`: add the three counting cases (14–16 above).
5. New `dashboard/src/lib/needs_you_view.js`: `pageOf`, `sortRows`, `readSort`/`writeSort`, `pillFor`, `kindLabel`, `projectNameFor`, `mergeRefresh`.
6. New `dashboard/test/needs_you_view.test.js`: cases 1–9 above, written and failing before step 5's implementation lands (TDD).
7. New `dashboard/src/components/NeedsYouSection.jsx`: presentational `NeedsYouList` (props-only) + thin stateful wrapper (saved-state-first via `saved_state.js`, trigger-based refresh, sort/page state wired to step 5's pure helpers).
8. Render tests (17–21 above) in `render_smoke.test.jsx` or a new `needs_you_section.test.jsx`, against the presentational `NeedsYouList` with fixed props.
9. `dashboard/src/components/ActivityBoard.jsx`: pass `onOpenTicket` to `DashboardHome`.
10. `dashboard/src/components/DashboardHome.jsx`: accept `onOpenTicket`, mount `<NeedsYouSection>` above the "Project Boards" heading; extend its existing loading-state smoke test (21).
11. `npx vitest run` inside `dashboard/` (not a repo-wide `pytest -q` — the repeated 1200s timeouts on earlier attempts came from `pytest -q` over `lib/tests`, which this repo's own CI deliberately excludes for needing machine-local state/heavy ML deps unrelated to this ticket; this ticket touches only `dashboard/`, so scope verification to `dashboard/`'s own test command).
12. `npm run build` in `dashboard/`, then use the existing `dashboard/scripts/capture_screenshot.mjs` (+ `cdp_capture.js`/`screenshot_capture.js`) to capture the three required screenshots: list populated, list empty, a ticket opened from a row — extending the script with a click/navigate step if its current single-shot landing capture can't reach the "ticket opened" state unassisted.
13. Open the PR with before/after note on the `overview()` miscount, and the screenshots from step 12 — no Decisions section needed (see above).