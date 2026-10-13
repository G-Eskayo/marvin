I have everything I need. Here's the revised plan.

## North-star fit

**Reuses before adding:** The ranking backend from #330 (merged) stays untouched except for one real gap it never had: `rankNeedsYou`'s rows carry no `project` field, yet #411's own "Done when" requires "a `project:<id>` ticket shows under its project." `board.js`/`boards.js` already derive this (check labels for `project:` prefix, else `projectIdOf(repo)` from the already-exported `src/lib/projects.js`) — I reuse that exact derivation, not invent one. `relations_service.js`'s `overview()`/`needsYou()` wiring is **already correct** in the working tree (import, `b.tickets`, synchronous call all check out) — the previous review's finding #1 no longer applies; I keep it as-is and only add the regression test that pins it. The frontend reuses `DashboardHome.jsx`'s load/loading/error scaffolding, the `formatRelativeTime` helper, the real `onOpenTicket(repo, number)` two-arg call shape (confirmed from `App.jsx`/`ProjectBoard.jsx`/`NextUpQueue.jsx` — **not** the object-shaped call the last attempt used, which was silently broken), the real `window.api.triggers.on((t) => ...)` single-callback-with-topic-check idiom (confirmed from `ProjectBoard.jsx`'s `WaitingOnYou`/board-load effect — **not** the `on('activity', cb)` two-arg shape the last attempt invented), the existing `<select>` styling (`PortfolioHub.jsx`), and the existing severity colour classes (`bg-red-950/text-red-300`, `bg-orange-950/text-orange-300`, `bg-neutral-800/text-neutral-400`, used across 16 files) — not a new palette.

**Correcting the ticket's own "existing colours" framing:** no component currently ties those three colours to p0/p1/p2/p3 specifically (`CompletedView.jsx`'s `TAG_STYLE.priority` is one flat orange for every priority label). Gil's comment is the actual spec — a new tri-tier mapping using already-present classes — not literal reuse of a pre-existing mapping. I'm correcting that claim rather than repeating it.

**Simplest sufficient approach, now genuinely revised:** one pure module (`needs_you_view.js`) for sort/paginate/pill/cache/sort-persistence/fetch-reducer, a thin stateful wrapper, a presentational list component exported separately so it can be tested with direct props (the real bug in the last attempt's tests: they rendered the stateful wrapper, which only ever shows "Loading projects" under SSR, and asserted that string while believing they'd tested the section). No new IPC, no new dependency, one tiny addition to `needs_you.js` for `project`.

**Tokens:** fixes 5 concrete must-fix defects plus 2 more I found by re-deriving the real collaborator contracts (`onOpenTicket`, `triggers.on`) instead of trusting the last attempt's plan — spending the read time now is what prevents a 4th failed iteration.

**User capability:** unchanged from the original fit — this only surfaces and ranks, Gil still decides and answers in place.

## Decisions

None. Every open question in the ticket body was answered in Gil's 2026-10-13 comment (rows/pagination, empty state, pill colours + kind label, sort + persistence, saved-state-first load). No new ambiguity was introduced by the fixes below — the `onOpenTicket` and `triggers.on` corrections are *bugs against an existing, unambiguous contract*, not design choices.

## What's actually wrong, file by file (corrects the prior design doc)

1. **`relations_service.js`** — already fixed in the working tree (import present, `b.tickets` used, `rankNeedsYou` called synchronously without `await`). No code change. Keep test 18 (sum of `overview()[repo].needsYou` across repos `===` `(await needsYou()).length`) as the regression pin the last review asked for.

2. **`needs_you.js`** — real gap: rows have no `project` field. Add it: for each ticket, scan labels for a `project:` prefix (`boards.js`'s exact pattern) and use the suffix; else `projectIdOf(t.repo)` (import from `../../src/lib/projects.js`, matching `boards.js`'s import path). Exposed automatically through `relations_service.js`'s existing pass-through — no further plumbing.

3. **`needs_you_view.js`**:
   - `paginate`: clamp `page` into `[1, totalPages || 1]` before slicing (stale page after the list shrinks must not return an empty page while still claiming more).
   - `sortRows`: drop the invented `'kind'` key (never asked for); add `'project'` (alphabetical by `row.project`, stable for ties). Keep `'default'` (no-op, trusts #330's own order), `'priority'`, `'age'`. These four map 1:1 to Gil's four options (Unblocks most / Priority / Oldest / Project).
   - `priorityPill(priority)`: return a **CSS class string** (`bg-red-950 text-red-300` / `bg-orange-950 text-orange-300` / `bg-neutral-800 text-neutral-400` for p0/p1/p2-or-p3-or-null), not display text. There is one pill per row, not two.
   - `kindLabel(kind)`: fix text to Gil's exact words — `'needs answer'` for `needs-info`, `'needs you'` for `ready-for-human`.
   - `readCache`: validate `Array.isArray(parsed)`, return `null` otherwise (valid-but-wrong-shaped JSON, e.g. `{}`, must not crash `rows.length`/`.map` downstream).
   - `applyFetch`: add `requestId` tracking. `FETCH_START` payload carries the caller-generated id and sets `state.requestId` to it; `FETCH_SUCCESS`/`FETCH_ERROR` only apply when `payload.requestId === state.requestId`, else return `state` unchanged (the newest in-flight fetch always wins, regardless of resolution order). `SET_SORT` also resets `page` to 1 (internal consistency, not a Gil-visible design choice).

4. **`DashboardHome.jsx`**:
   - Split `NeedsYouList` into a pure presentational piece that takes `{ rows, loading, error, lastFetch, sortKey, page, pageSize, onSort, onPageChange, onOpenTicket, now }` — nothing it does touches `window`. Export it so tests can drive it with props directly.
   - One pill per row: `className={priorityPill(row.priority)}`, text `{kindLabel(row.kind)}`. Remove the separate `kindLabel` badge that currently exists alongside it.
   - Show `row.project` where the row currently shows `row.repo`.
   - Add Prev/Next buttons wired to `onPageChange`, disabled at the bounds; keep "Page N of M".
   - Add the sort `<select>` (reusing `PortfolioHub.jsx`'s exact class string), options "Unblocks most" (`default`) / "Priority" (`priority`) / "Oldest" (`age`) / "Project" (`project`), wired to `onSort`.
   - Add a small status line: `formatRelativeTime(lastFetch)` as "updated Xs ago" when idle, "updating…" while `loading && rows.length > 0`, and when `error && rows.length > 0` append "— showing saved data" rather than hiding the list (today it's silently swallowed).
   - `NeedsYouSection` (stateful wrapper): rename the local `fetch` function (shadows global `fetch`) to `refresh`; generate `requestId` via a `useRef` counter per call; fix `window.api.triggers.on(...)` to the real single-callback shape: `window.api.triggers.on((t) => { if (t.topic === 'activity') refresh() })`; guard against dispatching after unmount with a `let live = true` flag mirroring `ProjectBoard.jsx`'s existing idiom; fix row click to `onOpenTicket?.(row.repo, row.number)` (two positional args, matching the real contract — the object-shaped call was a silent break).

5. **`ActivityBoard.jsx`** — already correct (`onOpenTicket={onOpenTicket}` one-liner, confirmed against the real preload contract). No change.

6. **`render_smoke.test.jsx`** — replace the test-25 "DashboardHome renders NeedsYouSection" (which only asserts "Loading projects") and the duplicated unit tests (21–25 previously just re-ran `needs_you_view` unit tests) with real prop-driven renders of the new presentational component: populated list, empty state, loading-vs-empty distinguishable, pagination controls shown/hidden/clickable, sort `<select>` present with the right options, one pill per row with correct colour+text.

## Tests first

**`dashboard/test/needs_you.test.js`** (extend existing file, same fixture style):
1. A ticket with a `project:finance-os` label in `G-Eskayo/marvin` → `row.project === 'finance-os'`.
2. A ticket with no `project:` label → `row.project === projectIdOf(t.repo)` (e.g. `'marvin'` for `G-Eskayo/marvin`).

**`dashboard/test/needs_you_view.test.js`** (fix/extend existing file):
3. Pagination edges exactly as Gil listed: 0/5/6/11 items.
4. `paginate` with `page` beyond the last page (stale page after the list shrinks) → clamps to the last valid page, controls never claim more than exists.
5. Sort `'project'` → alphabetical by `row.project`, stable for ties (replaces the old, never-requested `'kind'` sort test).
6. Sort `'default'`/`'priority'`/`'age'` — keep existing tests 1–3, unchanged, still valid.
7. Unknown/corrupted sort key → falls back to input order, never throws (keep existing test).
8. `priorityPill('p0'/'p1'/'p2'/'p3'/null)` → red/orange/grey/grey/grey CSS classes (not "Critical"/"High" text — rewritten from the old wrong-shaped test).
9. `kindLabel('needs-info')` → `'needs answer'`; `kindLabel('ready-for-human')` → `'needs you'` (rewritten from the old wrong text).
10. Cache round-trip, null storage, storage that throws on `getItem`/`setItem` — keep existing tests.
11. `readCache` with valid JSON that isn't an array (e.g. `{}`) → `null`, not a downstream crash (new — the review's "note", promoted to must-fix since it's a real crash path).
12. Huge input (a few hundred synthetic rows) through sort + paginate — keep existing test.
13. **Stale-response guard:** `FETCH_START` with `requestId: 1`, then `FETCH_START` with `requestId: 2`, then `FETCH_SUCCESS` with `requestId: 1` arriving last → ignored; `FETCH_SUCCESS` with `requestId: 2` → applied. Newest wins regardless of arrival order (new, replaces the old plan's untested promise).
14. `FETCH_ERROR` → `state.rows` untouched, `state.error` set (keep existing reducer test; this already worked — the bug was the UI never *surfacing* it, covered by test 19 below).
15. `SET_SORT` resets `page` to 1 (new).

**`dashboard/test/relations_service.test.js`** — keep tests 17–20 (needs-info counted, sum-equals-list-length cross-check, hold/pinned excluded, one-repo-failure isolation), already correct and already pin finding #1.

**`dashboard/test/render_smoke.test.jsx`** (rewrite tests 21–25, prop-driven against the new exported presentational component, not the stateful wrapper):
16. Populated rows render title, project (not repo string), the one-line ask, and the unblocks badge only when `count > 0`.
17. `rows: []` → renders "Nothing needs you".
18. `loading: true, rows: []` → renders a loading placeholder distinguishable from "Nothing needs you" (the #310 state-collapse class).
19. `loading: true, rows: [...]` (background refresh with cache present) → renders the list plus "updating…", never a blocking spinner; `error` set with `rows` present → list stays, "— showing saved data" shown (covers the silently-hidden-error defect directly).
20. Pagination: `totalPages > 1` → Prev/Next buttons render, disabled at page 1 / last page respectively, calling `onPageChange` with the right value.
21. Sort `<select>` renders all four options and calls `onSort` with the selected key.
22. One pill per row: p0 → red classes + "needs answer"/"needs you" text (not "Critical"); p1 → orange; p2/p3/null → grey. (Replaces the old split priority-badge/kind-badge test.)

**New regression tests for the two bugs this re-plan found (not in the original review, found by re-deriving the real contracts):**
23. Clicking a row calls `onOpenTicket` with `(repo, number)` as two positional arguments, not an object (regression for the broken navigation call).
24. A mock `window.api.triggers.on` capturing the registered callback: invoking it with `{ topic: 'activity' }` triggers a refetch; invoking it with `{ topic: 'mr' }` does not (regression for the wrong `on('activity', cb)` call shape — tests the single-callback contract, not a mock that would hide the real signature mismatch).
25. Unmounting `NeedsYouSection` while a fetch is in flight, then letting it resolve, does not dispatch or throw (misuse: component lifecycle vs. async race).

## Task List

1. `dashboard/electron/main/needs_you.js`: import `projectIdOf` from `../../src/lib/projects.js`; add `project` to each row (label `project:<x>` → `x`, else `projectIdOf(t.repo)`).
2. `dashboard/test/needs_you.test.js`: add tests 1–2 above.
3. `dashboard/src/lib/needs_you_view.js`: clamp `paginate`'s page; replace `'kind'` sort with `'project'`; rewrite `priorityPill` to return a CSS class; fix `kindLabel` text; validate array shape in `readCache`; add `requestId` tracking to `applyFetch`; reset `page` on `SET_SORT`.
4. `dashboard/test/needs_you_view.test.js`: rewrite tests 8–9 for the new pill/label contract, add tests 4, 5, 11, 13, 15; keep the rest.
5. `dashboard/src/components/DashboardHome.jsx`: split out an exported, pure presentational list component (pills, project label, pagination controls, sort `<select>`, updated/updating/error-with-cache status line); fix `NeedsYouSection`'s `fetch`→`refresh` rename, `requestId`-tagged dispatches, `window.api.triggers.on((t) => ...)` shape, `live` unmount guard, and `onOpenTicket?.(row.repo, row.number)` two-arg call.
6. `dashboard/test/render_smoke.test.jsx`: replace tests 21–25 with props-driven tests 16–22 above; add regression tests 23–25.
7. Confirm `dashboard/electron/main/relations_service.js` needs no change (already correct) — rerun test 18 to pin it.
8. `dashboard/src/components/ActivityBoard.jsx`: confirm no change needed (already correct one-liner).
9. Run the full `vitest` suite; fix any fallout.
10. Manually run the dashboard (`run` skill / dev server), capture simulator/app screenshots for the PR: list populated (several projects, all three pill colours, pagination and sort control visible), list empty ("Nothing needs you"), and a row tapped opening that ticket with `HumanTaskPanel`/`TicketReply` visible — required by the ticket's own "Done when."