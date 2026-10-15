## North-star fit

**Reuses before adding anything new:** the entire data layer from #330 (merged, closed) is already shipped and in production use — `needs_you.js: rankNeedsYou`, `relations_service.js: needsYou()`, IPC `activity:needsYou`, preload `activity.needsYou` all exist and work (verified by reading each file directly, not from the design doc's claims alone). The exact UI patterns this ticket needs already exist elsewhere and will be reused, not reinvented: `NextUpQueue.jsx`'s self-contained fetch/collapse/trigger-refresh shape, `MetricsPage.jsx` + `saved_state.js`'s `readSaved`/`writeSaved`/`ageText` for "draw the last state instantly, refresh behind it" (marvin#236, already fully tested in `github_timeline.test.js` — I don't need to re-test that primitive, only my use of it), `github_view.js`'s `readRange`/`writeRange` for "remember a UI choice between launches" (same shape for "remember sort"), and `mr_history_view.js`'s `pageOf` for "5 per page with page controls." `ActivityBoard.jsx` already threads `onOpenTicket` cross-project exactly the way #411 needs it (`NextUpQueue` already does this today) — wiring `DashboardHome` into the same prop is a one-line addition, not new plumbing.

**Simplest sufficient approach:** no new IPC, no new GitHub calls, no new polling loop — one new pure lib module, one new presentational component (fully testable via `renderToStaticMarkup` since it takes already-fetched rows as props), one thin self-fetching wrapper (untested beyond a loading-state smoke render, matching how `MetricsPage`/`ParallelToggle` are already treated in this codebase), and two small surgical fixes to already-correct files (`needs_you.js`, `relations_service.js`).

**Tokens:** spends a small amount once; saves every future "what's waiting on me" scan Gil currently does by eye across projects — exactly what #330/#411 exist to remove.

**Capability:** pure coaching — surfaces and ranks, never acts on a ticket, never answers for him. Leaves Gil strictly more able to see and choose, not more passive.

**Correcting the ticket's own stated fit:** the ticket doesn't carry a north-star-fit paragraph itself (that was #330's), but its acceptance bullet "a `project:<id>` ticket shows under its project" is **not yet satisfied by the existing code** — I verified `relations_service.js`'s `getBoardData` is wired to the raw `fetchBoardData` (`index.js:399`), not the cross-project-aware `loadBoard()` that `boards.js` uses for the real board view. So today, a ticket in repo A labeled `project:B` would show under A in the needs-you list, not B. This needs a small, genuinely new piece of logic (below) — it's not already built, contrary to what a reader might assume from #330's design doc (which predates #411 and doesn't mention this case at all).

## What exists vs what's missing

| Needed | Status |
|---|---|
| Ranking, transitive unblocks, missing-section derivation | **Exists**, tested (`needs_you.js`, `dashboard/test/needs_you.test.js`) |
| IPC + preload (`activity:needsYou`) | **Exists** (`index.js:426`, `preload/index.js:150`) |
| `relations_service.needsYou()` | **Exists** (`relations_service.js:125-128`) |
| Cross-project `onOpenTicket` navigation into a ticket's `TicketDrilldown` (so Gil can answer in place via `Decisions`/`HumanTaskPanel`/`TicketReply`) | **Exists**, same mechanism `NextUpQueue` already uses (`App.jsx:156`, `ActivityBoard.jsx`, `ProjectBoard.jsx:534-567`) |
| Renderer for the home screen | **Missing** — nobody calls `activity.needsYou()` from the UI |
| `project:<id>` ticket shown under its real project, not origin repo | **Missing** — `needs_you.js` has no notion of this; `relations_service`'s ticket source bypasses `boards.js`'s existing redistribution logic (`boards.js:175-189`) |
| "N needs you" counts including `needs-info` | **Missing/buggy** — `relations_service.js: overview()` (line 109) only counts `column === 'ready' && owner === 'human'`; `needs-info` tickets land in `column: 'backlog', owner: null` (`board.js:137`) and are never counted. Confirmed by reading `board.js` directly. |
| Saved-state-first render, remembered sort, pagination UI patterns | **Exist as generic primitives elsewhere**, not yet used for this screen |

## Design

**1. `dashboard/electron/main/needs_you.js`** (pure, surgical addition)
- Import `projectIdOf` from `../../src/lib/projects.js` (same cross-boundary import style already used for `parseHumanTask`).
- Add `projectIdFor(ticket)`: scans labels for `project:<id>`, returns the first match's `<id>`; else `projectIdOf(ticket.repo)`.
- Add a `projectId` field to each row returned by `rankNeedsYou`. Nothing else in the ranking/filtering/sorting logic changes.

**2. `dashboard/electron/main/relations_service.js`** — one surgical fix, scoped only to the literal "Also fix" bug (not conflated with the `project:<id>` display question, which is a separate, independently-testable concern):
- In `overview()`, replace the `column==='ready' && owner==='human'` tally for `needsYou` with a count derived from `rankNeedsYou(b.tickets)` grouped by `row.repo` (so `needs-info` is included and the count is guaranteed to equal the list for that repo). `review`/`blocked` tallies stay as they are — untouched, still correct.

**3. `dashboard/src/components/ActivityBoard.jsx`** — one line: pass `onOpenTicket` through to `DashboardHome`, exactly as it already does for `NextUpQueue`/`ProjectBoard`.

**4. New `dashboard/src/lib/needs_you_view.js`** (pure, no React, no IO — the fully-tested half of this ticket):
- `pageOf(rows, page, size = 5)` — same clamp/slice shape as `mr_history_view.js: pageOf` (not imported — two existing call sites with a third isn't yet "search for something to reuse before writing" territory per the composability guidance against abstracting for only two sites; this is a 4-line function, cheap to duplicate with the right domain name).
- `sortRows(rows, key)` — `'unblocks'` (identity, #330's own order), `'priority'`, `'oldest'`, `'project'` (by resolved project id/name, falling back to repo).
- `PRIORITY_PILL = { p0: 'red', p1: 'orange', p2: 'grey', p3: 'grey' }` plus a `pillFor(priority)` helper returning Tailwind classes or `null` for no/garbage priority.
- `kindLabel(kind)` → `'needs answer'` for `needs-info`, `'needs you'` for `ready-for-human` (Gil's exact wording, 2026-10-13 comment).
- `projectNameFor(row, boards)` — resolves `row.projectId` against the already-loaded `boards` list (`projectIdOf(b.repo) === row.projectId`), falling back to the repo's short name (mirrors `OtherProjects`'s existing fallback in `ProjectBoard.jsx:462`).
- `readSort`/`writeSort` — same try/catch shape as `github_view.js: readRange`/`writeRange`, key `'needsYou.sort'`, valid values gated the same way.
- `mergeRefresh(prev, result)` — pure reducer: on success, replaces rows; on failure, keeps `prev.rows` and attaches `error`. (This exists today only as untested inline logic in `MetricsPage.jsx`; extracting it here makes the ticket's explicit "a refresh failure keeps the saved list" requirement actually testable, which is the point of "verify fails when code changes without a test changing.")

**5. New `dashboard/src/components/NeedsYouSection.jsx`**:
- A thin stateful wrapper (mirrors `NextUpQueue.jsx`): `useState(() => readSaved(storage(), 'needsYou.rows'))` for instant first paint, `useState(() => readSort(storage()))` for remembered sort, `useState(0)` for page, fetches `window.api.activity.needsYou()` on mount and on `window.api.triggers.on(t => t.topic === 'activity' && load())` (same trigger `WaitingOnYou` already listens for — no new polling).
- Delegates all actual rendering to a pure presentational child, **`NeedsYouList`** (exported from the same file or a sibling), which takes `{ rows, boards, page, sort, onSort, onPageChange, onOpenTicket }` as props only — no fetching, no effects — so it is fully testable with `renderToStaticMarkup` and fixed fixtures, same tier as `GithubView`/`Decisions`.
- Empty state: exact copy `"Nothing needs you"` (Gil's words), one quiet line, section stays visible (not hidden).
- "updated Xs ago" / "updating…" note via `ageText`, never a blocking spinner — same as `MetricsPage`.
- Row click → `onOpenTicket(repo, number)`.

**6. `dashboard/src/components/DashboardHome.jsx`**: accept `onOpenTicket`, render `<NeedsYouSection onOpenTicket={onOpenTicket} />` above the `Project Boards` heading (Gil's placement: top of Activity home, above the project cards — this file *is* that screen, so this is the literal location).

## Decisions

None needed. Gil's 2026-10-13 comment answers every open question the ticket itself raised (row count/pagination, empty-state copy, priority-pill colours+kind label, default sort + alternatives + persistence, saved-state-first render). The remaining choices below are implementation judgment calls, not product choices, so I'm deciding them myself rather than inventing a button for them:
- `project:<id>` grouping affects only the **list's** display, not the home-card badge counts (kept decoupled, each independently testable) — scope decision explained above.
- Missing/garbage priority renders no pill (consistent with how every other badge in this codebase is conditionally rendered, e.g. `Card` in `ProjectBoard.jsx`).
- `unblocks` preview text reuses the existing comma-list-plus-overflow style already used by `OtherProjects`/`NextUpQueue`.

## Tests first

All in `dashboard/test/`, Vitest, fixture objects — no mocks of `rankNeedsYou`/`human_task.js` themselves (real collaborators, so a mock can't hide a regression in them).

**New: `dashboard/test/needs_you_view.test.js`** (pure logic, the bulk of the coverage):
1. `pageOf`: 0 items → `{page:0, pages:1, rows:[]}`; 5 items → 1 page of 5; 6 items → page 0 has 5, page 1 has 1; 11 items → 3 pages (5/5/1); out-of-range page clamps to the last valid page; negative page clamps to 0 — the exact "pagination edges (0, 5, 6, 11)" Gil asked for.
2. `sortRows`: `'unblocks'` preserves input order (identity — #330's own ranking); `'priority'` puts p0 before p1 before p2/p3 before unlabelled, stable on ties; `'oldest'` puts the largest `ageDays` first; `'project'` groups/orders by resolved project id, not raw repo string.
3. `readSort`/`writeSort`: round-trips a valid value; garbage/missing storage value falls back to `'unblocks'`; throwing storage (`getItem`/`setItem` both throw) never throws, matches `readRange`'s own "throwing storage is ignored" test.
4. `mergeRefresh`: success replaces rows; failure with a prior successful result keeps the prior rows and sets `error`; failure with **no** prior result (first-ever load fails) leaves rows empty with an error, never throws — covers "a refresh failure keeps the saved list and shows its age" plus the empty-first-load case that comment missed.
5. `pillFor`: `'p0'`→red, `'p1'`→orange, `'p2'`/`'p3'`→grey, `null`/`undefined`/garbage string (`'p9'`, `''`)→no pill, never throws.
6. `kindLabel`: `'needs-info'`→`'needs answer'`, `'ready-for-human'`→`'needs you'`, unknown kind → doesn't throw, returns something non-crashing.
7. `projectNameFor`: a row whose `projectId` matches a registered board → that board's name; a `projectId` with no matching board (unregistered/foreign project) → falls back to the row's repo short name, never throws; empty `boards` list → same fallback.
8. Huge input: 500 synthetic rows through `pageOf`+`sortRows` together completes without stack issues and returns correct `pages`/ordering (mirrors needs_you.js's own "huge input" case at this layer).
9. Malformed row: a row missing `priority`/`unblocks`/`ask` fields (as if an older cached/saved-state blob predates a schema change) → `pillFor`/`kindLabel`/rendering helpers degrade gracefully, never throw — the "stale state" and "a person's/a prior version's mistake" cases.

**Extend `dashboard/test/needs_you.test.js`** (new cases on `rankNeedsYou`/a new `projectIdFor`):
10. A ready-for-human ticket in repo A labelled `project:B` → `row.projectId === 'B'`, not `projectIdOf('A')`.
11. No `project:` label → `row.projectId === projectIdOf(ticket.repo)`.
12. Self-referential `project:<own-id>` label → resolves to the same id, no special-case crash.
13. Malformed/empty `project:` label (`'project:'`, trailing colon, duplicate conflicting `project:` labels) → takes the first match, never throws.

**Extend `dashboard/test/relations_service.test.js`**:
14. A ticket with only `needs-info` (no `ready-for-human`) → `overview().needsYou` for that repo is `1`, not `0` (the literal "Also fix" bug, reproduced and fixed).
15. `overview().needsYou` for a repo with 2 `ready-for-human` + 1 `needs-info` (none hold/pinned) equals `3` — "counts equal list length," checked against the same `rankNeedsYou` output `needsYou()` itself returns for that repo.
16. A `hold`-labelled `ready-for-human` ticket is excluded from the count too (not just the list) — consistency between the two call sites.

**New: `dashboard/test/render_smoke.test.jsx` additions (or a new `needs_you_section.test.jsx`)** — presentational-only, fixed props, `renderToStaticMarkup` (house convention, no DOM/async):
17. List populated: 2 rows, one `p0`/`ready-for-human`, one `needs-info` with no priority → both pills, both kind labels, both asks render; red pill present, no pill for the unlabelled one.
18. List empty: `rows: []` → contains exactly `"Nothing needs you"`, section still present (not hidden/removed from the tree).
19. Pagination controls: 6 rows → page controls render ("Page 1 of 2" shape); 5 rows → no page controls (single page, matching `pageOf`'s "pages > 1" gate already proven in `mr_history_view`'s own UI).
20. A row's click handler is wired to call `onOpenTicket(repo, number)` with the row's own `repo`/`number` — proven via a `vi.fn()` prop and simulating the handler call directly on the rendered element's `onClick`, the same style other tests in this file use for handler wiring (no jsdom needed, since React element props are plain inspectable objects in the pre-SSR tree — or, if that proves awkward, assert via a small exported pure `rowProps(row)`/`onRowClick(row, onOpenTicket)` helper instead, keeping the click-wiring itself in `needs_you_view.js` and testable without any rendering at all).
21. `DashboardHome` + `NeedsYouSection` still render a sane initial/loading state and don't throw when mounted with no `window.api` stub beyond what the existing "renders a loading state on mount" smoke test already provides — extend that existing test rather than duplicating it.

**Explicit misuse/dependency coverage already satisfied by reuse, verified not re-derived:**
- `window.api.activity.needsYou()` rejecting → covered by `mergeRefresh`'s failure case (test 4) plus the untested-but-thin wrapper calling it exactly like `MetricsPage`/`NextUpQueue` already do (`.catch` to a safe default, same pattern).
- Repeated/cached calls (no extra GitHub traffic) → already proven by `relations_service.test.js`'s existing cache test; I'm not changing the caching trigger, so no new test needed there, only confirmed by re-reading it (done above).
- Concurrency: the only new client state (page/sort) is synchronous `useState`, no race possible; nothing to test beyond the pure functions already being pure.
- Wrong permissions / a repo failing to load → already covered by `relations_service.js`'s existing "one repo failing to load does not take the rest down" test, which `needsYou()` already shares the same `ready()`/`build()` path with — re-verified by reading `build()`'s try/catch (line 33-35), not re-derived.

## Task List

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