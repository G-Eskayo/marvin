## North-star fit

**Reuse before adding.** The ranked backend (`rankNeedsYou`, IPC `activity:needsYou`, preload `activity.needsYou`) from #330/PR #371 is untouched and fully covered — no need to re-derive it. The `projectFor`/`rankNeedsYou(projects)`/`relations_service.overview()` wiring already sitting uncommitted in this worktree is logically sound (verified against `boards.js`) and worth keeping. Navigation reuses `onOpenTicket(repo, number)`, already wired through `ActivityBoard`→`DashboardHome`. Saved-state-first reuses `saved_state.js`'s `readSaved`/`writeSaved`/`ageText` verbatim (ADR'd at #236/#417).

**Correction to the ticket's stated fit, re-verified:** Gil's answer #3 says "using the dashboard's existing priority colours" — confirmed (again) there is no per-level priority colour map anywhere else (`ProjectBoard.jsx`/`CompletedView.jsx` use one flat orange tag for every priority). Red/orange/grey are new tones reusing the dashboard's existing semantic vocabulary, not a pre-built scale. This correction was already right in the prior attempt; keeping it.

**Correction to the prior attempt's own plan:** its "Decisions" section asked Gil to choose how a `project:<id>`-labelled ticket should be counted (its labelled project vs. its physical repo). That is not an open decision — `dashboard/electron/main/boards.js:170-185` (`loadBoard`) already does this today: a `project:<id>` ticket is *removed* from its own repo's board and *added* to the labelled project's board via `fetchCrossProjectIssues`. Counting it under the labelled project (what the prior attempt already implemented) is the only choice consistent with where the ticket already visibly lives. No Decisions section is needed in this plan — see below.

**Root cause of the regression, found by reading the code (not guessed):** the diff sitting in this worktree has three concrete, verifiable bugs, not the honest "effects don't run under `renderToStaticMarkup`" limitation its own comments claim:

1. **Broken saved-state contract.** `saved_state.js`'s `readSaved` returns the *whole envelope* `{ at, value }` (confirmed against its own source and `MetricsPage.jsx:36`, which correctly reads `saved.value`). `NeedsYouList.jsx:76` instead reads `saved.rows` and `saved.at` directly — `saved.rows` is always `undefined` whenever real saved data exists. `sortRows(data.rows, …)` runs unconditionally on every render (line 118, *before* the loading/empty early-returns) and does `[...rows]` — spreading `undefined` throws synchronously. Any future render of this component with real localStorage content throws on mount.
2. **A non-existent IPC API.** The real preload (`dashboard/electron/preload/index.js:152-156`) is `triggers.on(callback)` — one argument, callback receives the raw `trigger` object, filtering is the caller's job (every other component does `window.api.triggers.on((t) => t.topic === 'activity' && load())`, e.g. `ProjectBoard.jsx:429`, `DocsExplorer.jsx:355`). `NeedsYouList.jsx:104/109` calls `triggers.on('activity', load, { cancelled: () => false })` — three arguments, an invented `{ cancelled }` option that doesn't exist. In the real app, `callback('activity')` inside `on()` would try to invoke the *string* `'activity'` as a function the instant any trigger fires, throwing inside an Electron IPC listener. This is exactly the shape of defect a code reviewer flags as "must-fix" (ticket history: "code review found must-fix issues" ×2) and, if the verification pipeline exercises the running app for the required screenshots, is a plausible source of the chronic "timed out after 1200s" pattern across many earlier attempts on this same ticket.
3. **No real overlap guard**, despite the prior design doc listing it as test case #13 to write: `load()` has no sequence token, so an out-of-order resolution (trigger fires mid-fetch) lets a stale response overwrite a newer one. Never implemented, only promised.

None of these three bugs are reachable by the current (`.skip`'d) component tests, which is itself the tell: the prior attempt wrote tests, watched them fail against real behavior, and skipped them instead of fixing the component — exactly what "Verify fails when code changes without a test changing" exists to catch. `.skip` is banned from this plan.

**Simplest sufficient approach, corrected:** fix the three bugs above using patterns this codebase already has working examples of (`MetricsPage.jsx` for the saved-state shape, `ProjectBoard.jsx`/`DocsExplorer.jsx` for `triggers.on`, the `let cancelled = false` / ref-token idiom used in `ResourcesPanel.jsx`/`NextUpQueue.jsx`/`DeviceColumns.jsx` for overlap guards — generalized to a counter since two in-flight calls, not one, must be disambiguated). Keep every pure helper in `needs_you_view.js` (already correctly designed and tested) and make `NeedsYouList.jsx` a thin, correct consumer of it. Component tests assert only what this codebase's own convention already proves is testable under `renderToStaticMarkup` — the *synchronous* initial render (lazy `useState` initializers run even in static rendering; `useEffect` never does) — matching `DashboardHome`'s own "renders a loading state on mount" test and `CompletedView`/`TicketAgentsPanel`/`ProfilesPanel`'s "renders nothing/loading until effect runs" tests. No invented testing-library dependency, no skips.

**Where it spends tokens:** this re-plan spent its budget reading every file end-to-end against the *real* contracts it touches (`saved_state.js`, `preload/index.js`, `boards.js`) rather than trusting the prior attempt's own comments about them — that's precisely where the previous two code-review rejections came from. The implementation itself is smaller than before: one `useEffect` for triggers (not two), no fake options object, no skipped tests to apologize for in review.

**User capability:** unchanged from the prior (correct) assessment — this surfaces work Gil already owns (answering tickets) that's currently invisible, making him more effective at a task he already does, not more passive.

## No Decisions section

Every question the ticket raised was answered by Gil in his 2026-10-13 comment (row count/pagination, empty state, pill colours, sort control + persistence, saved-state-first). The one item the prior attempt escalated as a Decision (cross-project counting) is settled by existing, running code (`boards.js`'s `loadBoard`/`fetchCrossProjectIssues`), not a matter of taste. Nothing here needs the owner's input.

## Tests to write first

**From the ticket's own "Done when" list:**
1. Tickets ranked across several repos appear correctly, each attributed to the right repo/project (already covered: `needs_you.test.js` `projectFor`/`rankNeedsYou` cases — keep as-is, they're correct).
2. `hold`/`pinned` labelled tickets are skipped (already guaranteed upstream; keep the existing pass-through check).
3. A `project:<id>`-labelled ticket shows under its labelled project, not its physical repo (already covered in `needs_you.test.js` + `relations_service.test.js`; keep).
4. Home-card/strip counts equal the rendered list's length, including `needs-info` (already covered in `relations_service.test.js`; keep).

**From Gil's 2026-10-13 comment:**
5. Pagination edges: 0, 5, 6, 11 items (already covered in `needs_you_view.test.js`'s `paginate` suite — add the 0/11-item cases explicitly, currently only 2/3/6 are covered).
6. Saved list renders before the refresh resolves — **rewritten as a real, non-skipped test**: with `{at, value:{rows:[...]}}` in mocked `localStorage`, `renderToStaticMarkup(<NeedsYouList .../>)` must show the populated rows (this is the direct regression test for Bug A — it fails today against the current buggy component and must pass after the fix).
7. A refresh failure keeps the previously-saved list and shows its age — tested at the pure-function level only (`mergeNeedsYouResult`, already covered) since the effect itself can't run under this harness; **do not** assert this through the component.
8. The chosen sort persists across a simulated relaunch — tested at `readSortChoice`/`writeSortChoice` level (already covered).

**Misuse the section didn't name, plus the regression's own root causes:**
9. **(Bug A regression test)** A saved entry with the correct envelope shape but no `rows` in `value` (`{at, value:{}}` — simulating a pre-#411 saved blob under a reused key, or a future field rename) renders the empty/"Nothing needs you" state, not a crash. This is the direct test for the `saved.rows` vs `saved.value.rows` defect.
10. Malformed/unparseable saved JSON (`'{ broken'`) — `readSaved` already catches this and returns `null`; component must render its normal "reading…" pre-fetch state, not throw.
11. Zero needs-you tickets, with a previously-saved *empty* rows array (`{at, value:{rows:[]}}`) → renders "Nothing needs you" synchronously (this is the one zero-state reachable without an effect; the all-localStorage-empty case renders the pre-fetch loading state instead, and both are asserted, as two different and correctly-distinguished cases).
12. **(Bug C regression test)** The `useEffect` that subscribes to triggers calls `window.api.triggers.on` with **exactly one argument** (a predicate function), matching `ProjectBoard.jsx`'s real usage — assert the mock is called with `(fn)` where `fn.length === 1`, not with a topic string and options object. This is a direct regression test for the invented 3-arg API.
13. **(overlap guard, now actually implemented)** Two overlapping `needsYou()` resolutions, where the first (older) call's promise resolves *after* the second (newer) one — tested as a pure function: `load`'s guard logic is extracted so it can be driven by hand with out-of-order resolution, asserting the final state reflects the newer response, not the older one. (Previously promised, never implemented — now it is both coded and tested.)
14. A large list (200 rows) paginates correctly without ever mapping more than one page's worth of rows (already covered at the `paginate` pure-function level; add a 200-row case).
15. `window.api.boards.list()` failing independently of `activity.needsYou()` — `projectName` already degrades to the repo short name when `boards` lookup misses; add the case where `boards` itself is `undefined`/empty (already partially covered — add the explicit "boards never loaded yet" case, since `DashboardHome` can call `NeedsYouList` with `cards` still being computed from a partial state).
16. `localStorage` missing, full, or throwing on read/write — both `readSaved`/`writeSaved` (existing contract, reused) and `readSortChoice`/`writeSortChoice` (already covered) must degrade to defaults, never throw.
17. A corrupted/unrecognised persisted sort value falls back to `'unblocks'` (already covered in `needs_you_view.test.js`).
18. Changing the sort control resets to page 0 (component-level behavior — not independently testable under this harness since it requires a click event; document this explicitly as a manual/screenshot-verified behavior rather than silently dropping it).
19. A ticket with both `needs-info` and `ready-for-human` gets exactly one `project` resolution and one pill (kind precedence already exists in `rankNeedsYou`; existing coverage confirms no fork).

## Task List

**Backend (already correct in this worktree — keep, no changes)**
1. `dashboard/electron/main/needs_you.js`: `projectFor` + `rankNeedsYou(projects)` — keep as-is.
2. `dashboard/electron/main/relations_service.js`: `overview()`/`needsYou()` passing `getProjects()` through — keep as-is.
3. `dashboard/test/needs_you.test.js`, `dashboard/test/relations_service.test.js`: keep the already-added cases; add the 0/11-item pagination edge case noted in item 5 above to `needs_you_view.test.js` instead (it's a frontend pure-function concern).

**Frontend — pure helpers (`dashboard/src/lib/needs_you_view.js`, already mostly correct — keep, extend)**
4. Keep `paginate`, `sortRows`, `pillFor`, `projectName`, `readSortChoice`, `writeSortChoice` as-is (already correct and tested).
5. Rewrite `mergeNeedsYouResult` to accept and track a request sequence so overlapping resolutions can be adjudicated purely: `mergeNeedsYouResult(prev, result, { now, seq, latestSeq })` (or equivalent) — stale (`seq < latestSeq`) results are dropped entirely, not merged.
6. `dashboard/test/needs_you_view.test.js`: keep existing coverage; add the 0/11-row pagination cases (item 5) and the overlap-guard cases (item 13) for the revised `mergeNeedsYouResult`.

**Frontend — component (`dashboard/src/components/NeedsYouList.jsx` — fix the three bugs, do not just re-skip)**
7. Fix the saved-state read: `saved ? { rows: saved.value?.rows ?? [], error: null } : { rows: [], error: null }`, matching `MetricsPage.jsx`'s pattern exactly.
8. Fix the trigger subscription to the real one-argument API: `useEffect(() => window.api.triggers.on((t) => (t.topic === 'activity' || t.topic === 'mr') && load()), [])` — delete the invented `{ cancelled }` option and the second `triggers.on` call.
9. Add a request-sequence `useRef` counter in `load()`: increment on each call, pass the captured token through to the new `mergeNeedsYouResult` signature, so a stale response is dropped instead of overwriting newer state.
10. Keep the `setInterval` "keeps 'updated X ago' honest" tick — this matches the established convention identical in `MetricsPage.jsx:57` and `ProjectBoard.jsx:80`; it is not a defect, and the prior design doc's instinct to treat it as a hang risk was wrong (confirmed: no test exercises a mount, so it's never created during the test run either way).
11. Keep pagination (5/page), sort control (4 options), empty state, row click → `onOpenTicket(row.repo, row.number)` — unchanged from the prior attempt's design, which was correct here.

**Frontend — component tests (`dashboard/test/needs_you_list.test.jsx` — remove every `.skip`, fix the wrong assertions underneath them)**
12. Replace the file's skipped tests with real, passing ones asserting only synchronously-reachable states (no effect required): no saved data → "Reading what needs you…" (not "Nothing needs you" — the prior attempt's skipped assertion was actually wrong, which is likely why it got skipped instead of fixed); saved data with populated rows → pill/title/project/ask/unblocks render (direct Bug A regression test); saved data with an empty rows array → "Nothing needs you"; saved envelope present but `value.rows` missing (Bug A regression, item 9); malformed JSON → same as no-saved-data case; `triggers.on` called with a single-argument predicate (Bug C regression, item 12).

**Wiring (already correct in this worktree — keep)**
13. `dashboard/src/components/DashboardHome.jsx`: `onOpenTicket` prop + `<NeedsYouList boards={cards} onOpenTicket={onOpenTicket} />` placement above "Project Boards" — keep as-is.
14. `dashboard/src/components/ActivityBoard.jsx`: pass `onOpenTicket` through to `DashboardHome` — keep as-is.

**Done-when evidence (not automatable, listed so it isn't dropped)**
15. Simulator/app screenshots in the PR: list populated, list empty, a ticket opened from a row, and the sort control actually changing the order and resetting to page 0 on click (item 18, verified manually since it can't run under this test harness).