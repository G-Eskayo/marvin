## North-star fit

**Reuses before adding anything:** the ranking backend (`needs_you.js` `rankNeedsYou`, IPC `activity:needsYou`, preload `activity.needsYou`) and the ADR 0060 `projectId` resolution it already computes — both already correct in this worktree (verified by reading the files, not assumed); the saved-state pattern (`saved_state.js` `readSaved`/`writeSaved`/`ageText`, used by `MetricsPage.jsx`); the dashboard's existing `bg-X-950`/`text-X-300` severity-pill idiom (`ProjectBoard.jsx` `TAG_STYLE`, `HealthDashboard.jsx` `SEVERITY_COLOR`); `projectIdOf` (`src/lib/projects.js`) for matching a row's `projectId` to a board, same function `boards.js` already uses to assign `board.status`; and the **real** trigger-subscription shape used by every other polling component (`ProjectBoard.jsx:429`, `HealthDashboard.jsx:177`: `window.api.triggers.on((t) => t.topic === 'activity' && load())`, cleanup returned directly) — the previous attempt invented a different, non-existent two-argument call shape.

**Why this is the simplest sufficient approach:** `activity.needsYou()` already returns the full, unpaginated, backend-ranked row set, so pagination/sort/project-name resolution stay pure client-side array functions — no new IPC, no wire params. The two backend files flagged by code review (`relations_service.js`, `needs_you.js`) need **no changes this round** — read directly, both already contain the fix (`overview()` already imports and calls `rankNeedsYou`, `needs_you.js` already computes ADR-0060 `projectId`), and `relations_service.test.js`/`needs_you.test.js` already assert it end-to-end (tests `#8`–`#12`, `#28`–`#30`). The real defects are confined to the two new files (`needs_you_view.js`, `NeedsYouList.jsx`) and one weak test. Fixing them is smaller than last attempt's diff, not bigger: `applyRefresh` is **deleted** rather than patched, since `paginate`'s own clamp already satisfies "don't yank the page" once `NeedsYouList` stops re-sorting and overwriting its canonical row order on every sort/refresh (the real root cause of the page-reset bug — see below).

**Tokens:** spends a little now re-deriving the component's state model correctly (canonical backend-order rows, sorted only at render time) instead of patching symptoms; saves downstream because every behaviour (pagination edges, sort switching back to "unblocks" after trying "Priority", refresh-while-reading, pill text/colour, project-name fallback) becomes one pure function this repo already knows how to test cheaply (`renderToStaticMarkup`, no new test harness).

**User impact:** unchanged from the ticket's own framing — this surfaces already-answerable work Gil would otherwise miss (Seal Speak #406/#408/#410 never showed up anywhere); it doesn't act for him. More capable, not more passive.

The ticket itself states no explicit north-star fit; Gil's answer **#5** invokes the "whole dashboard" saved-state-first direction from `#236`, confirmed correct against the code (`saved_state.js` exists for exactly this).

## What's actually broken, read from the current files (not assumed)

Confirmed by reading `dashboard/electron/main/relations_service.js` and `dashboard/electron/main/needs_you.js` directly: both review findings about them are **already fixed** in this worktree — the import exists (`relations_service.js:3`), `overview()` groups `rankNeedsYou` rows by `row.repo` (line 112-116), and `needs_you.js` computes `projectId` per ADR 0060 (lines 198-209) with existing passing-shaped tests `#28`–`#30`. **No changes to these two files this round.** The remaining four findings are all real, confirmed by reading `needs_you_view.js` and `NeedsYouList.jsx`:

1. **`applyRefresh` resets to page 1 on same-length refresh** (`needs_you_view.js:43`) — confirmed. Root cause is deeper: `NeedsYouList.jsx` stores the **sorted** array as `data` and overwrites it on every load/sort (`load()` line 33-34, `handleSortChange` line 61-62), so there's no stable canonical order to diff against, and once you switch to "Priority" you can never get back the original backend "unblocks" order. Fix: keep `rows` as the untouched backend order in state; derive the displayed array via `sortRows(rows, sortOrder, boards)` fresh on every render; delete `applyRefresh` and let `paginate`'s existing clamp (`Math.min(page, totalPages)`) be the only clamping logic.
2. **Page size hard-coded to 10** (`NeedsYouList.jsx` calls `paginate(sorted, currentPage, 10)`) instead of the design's 5. Fix: `export const PAGE_SIZE = 5` in `needs_you_view.js`, used by both the component and its tests (no literal `5`/`10` duplicated).
3. **Sort set is `impact`/`priority`/`age`, no `project`, and `impact` re-sorts already-ranked rows.** Fix: `SORT_ORDERS = ['unblocks', 'priority', 'oldest', 'project']`; `'unblocks'` is a passthrough (returns the input array unchanged — no re-sort, no tiebreak override); `'project'` added, resolving via `resolveProjectName`.
4. **`priorityPill` wrong colours/missing kind text/no pill for no-priority rows** (`needs_you_view.js:51-57`). Fix: reuse the existing grey/red/orange idiom — p0 `bg-red-950 text-red-300`, p1 `bg-orange-950 text-orange-300`, p2/p3 **and no-priority** `bg-neutral-800 text-neutral-400` (matches `TAG_STYLE.state`); label becomes `"P{n} · needs you"` / `"P{n} · needs answer"`, or just `"needs you"`/`"needs answer"` with no `Pn` prefix when there's no priority (Decision `no-priority-pill` Option A, implemented as the shipped default pending Gil's confirmation).
5. **`resolveProjectName` is fed a broken `{id, name}` array built from `board.id`** (`NeedsYouList.jsx:77`) — board objects carry `repo`/`name`/`status`, never `id` (confirmed in `boards.js`/`DashboardHome.jsx`), so this always falls back to the raw id. Fix: pass `boards` straight through; `resolveProjectName(row, boards)` matches via `projectIdOf(board.repo) === row.projectId` (ADR 0060's own matching rule), falling back to `row.repo.split('/')[1]` — the exact fallback `ProjectBoard.jsx`'s `OtherProjects` already uses. `boards` already includes archived boards (`DashboardHome.jsx` filters archived client-side from one combined list), so archived-board resolution needs no extra plumbing.
6. **The trigger subscription uses an API shape that doesn't exist**, found while reading the real preload (`electron/preload/index.js:152-158`: `triggers.on(callback)` takes one callback receiving `{topic, ...}`). `NeedsYouList.jsx:48` calls `window.api.triggers?.on?.('activity', load)` — passing the string `'activity'` as the callback. Every real `trigger` event would call `callback(trigger)` where `callback` is a string, throwing `TypeError: callback is not a function` inside the IPC listener on every background refresh. No existing test caught this because nothing exercises the real `triggers.on` call signature. **Must-fix**, found by reading the actual collaborator rather than trusting the component's own mock-shaped assumption — exactly the gap "test against the real collaborator" exists to catch.
7. **Empty-state copy doesn't match Gil's literal text.** He asked for exactly `"Nothing needs you"` (answer #2); the code shows `"Nothing needs you right now"`. Per the no-unapproved-UI-changes rule, match the approved copy exactly.
8. **Test #24 is not a test.** It renders `DashboardHome` and asserts only `'Loading projects'`, which the pre-existing "renders a loading state" test already covers — it can't detect `NeedsYouList` being absent, moved, or mis-ordered.

## Tests to write first

All in `dashboard/test/needs_you_view.test.js` (rewritten for the new function signatures) unless noted. `needs_you.test.js` and `relations_service.test.js` are left as-is — already cover their files' (unchanged) behaviour.

**Pagination (`paginate`, `PAGE_SIZE = 5`):**
1. 0 items → 1 page, no rows.
2. Exactly 5 items → 1 page, all 5 shown.
3. 6 items → 2 pages (5 + 1).
4. 11 items → 3 pages (5 + 5 + 1).
5. Garbage `page` (`-1`, `0`, `NaN`, `99` beyond range) clamps into `[1, totalPages]` instead of throwing or returning empty.
6. Non-integer/garbage `pageSize` (`0`, `-5`, `NaN`, `'x'`) falls back to `PAGE_SIZE` rather than throwing or dividing by zero.
7. Large input (500 rows) doesn't throw and returns the right `totalPages`.

**Sorting (`sortRows`):**
8. `'unblocks'` is a strict passthrough — output array `toEqual` the input order, byte-for-byte, including when priorities/ages would reorder under another mode (proves no re-sort).
9. `'priority'` orders p0 < p1 < p2/p3 < no-priority.
10. `'oldest'` orders higher `ageDays` first.
11. `'project'` orders by `resolveProjectName(row, boards)`, case-insensitive; an unregistered project falls back to the repo string and sorts by that.
12. Malformed row (`priority: undefined`, `ageDays: NaN`, missing `unblocks`) doesn't throw and sorts into the safe/last bucket.
13. Empty array input doesn't throw for every sort order.
14. 500-row input sorts correctly and quickly for every order (no accidental O(n²) crash under misuse-scale input).

**Priority pill (`priorityPill(priority, kind)`):**
15. p0/`ready-for-human` → red class, label `"P0 · needs you"`.
16. p1/`needs-info` → orange class, label `"P1 · needs answer"`.
17. p2 and p3 → grey class (same class for both).
18. No priority (`null`/`undefined`) + each kind → grey class, label is just the kind text, no `"Pn"` prefix (locks in Decision `no-priority-pill` Option A as shipped default).

**Project resolution (`resolveProjectName(row, boards)`):**
19. `projectId` matching a registered board (status `active`) → that board's name.
20. `projectId` matching an **archived** board → still resolves to its name (ADR 0060).
21. `projectId` with no matching board → falls back to `row.repo.split('/')[1]`.
22. `boards` is `null`, `undefined`, or `[]` → falls back gracefully, never throws.
23. Case-insensitive project-id matching is **not** required (ids are already normalized by `projectIdOf`), but mismatched case in `row.projectId` itself (a malformed/stale row) still falls back without throwing.

**Sort preference persistence (`readSortPref`/`writeSortPref`):**
24. Round-trips through a storage-like object.
25. Invalid/unknown stored value falls back to `'unblocks'`.
26. `storage.setItem` throwing (quota/private window) doesn't throw out of `writeSortPref`.
27. Missing/undefined `storage` doesn't throw for either function.

**Component behaviour (`NeedsYouList.jsx`, pure-function-level — this repo's existing testing bar; no new test harness):**
28. `makeRowClickHandler(row, onOpenTicket)` calls `onOpenTicket(row.repo, row.number)` — pure callback-arg test.
29. **The real trigger API shape, not a mock that would hide the bug:** a fake `window.api.triggers.on` that mimics the preload exactly — `on: (cb) => { registeredCb = cb; return () => { offCalled = true } }` — is installed before rendering/mounting logic runs; asserting the subscribed callback is a function (not the string `'activity'`) and that invoking it with `{ topic: 'activity' }` calls `load` without throwing `TypeError: callback is not a function`. This is the regression test for finding #6 — it fails against the current `window.api.triggers?.on?.('activity', load)` call and passes once the call becomes `window.api.triggers.on((t) => t.topic === 'activity' && load())`.
30. A background refresh that returns the **same number of rows** (the common case: nothing changed) does **not** reset `currentPage` away from where the person is reading — directly exercises the state-model fix (canonical `rows` kept separate from the sorted/paginated view), replacing the deleted, bug-locking `applyRefresh` test.
31. A refresh rejection (`window.api.activity.needsYou()` rejects) leaves the previously saved `rows`/`updatedAt` unchanged — only `loading` flips back to `false`. Covers IPC/dependency failure.
32. A saved-state row shaped like the pre-ADR-0060 schema (no `projectId` field — an app-upgrade stale-state case) renders/sorts without crashing.
33. Initial render (no fetch resolved yet, env has no `window`/localStorage — this repo's actual node-environment test constraint) renders the quiet empty state, not a spinner, not a crash.

**`render_smoke.test.jsx` — fixing test #24, the one genuinely missing coverage:**
34. `DashboardHome` rendered **with** `onOpenTicket` contains the literal string `"Nothing needs you"` (the only state reachable in this SSR/node-only test environment, confirmed — `window` doesn't exist here so saved-state is always empty) **before** `"Loading projects"` in the HTML string (`indexOf` comparison — proves placement above the boards section, not merely presence).
35. `DashboardHome` rendered **without** `onOpenTicket` does **not** contain `"Nothing needs you"` — proves the conditional wiring is real and test #34 isn't trivially true regardless of whether `NeedsYouList` is mounted.

Verify-fails-without-a-matching-test: every behavioural line above is pinned to a named pure function (`paginate`, `sortRows`, `priorityPill`, `resolveProjectName`, `readSortPref`/`writeSortPref`, `makeRowClickHandler`) or a literal string assertion on rendered markup, so a silent revert of any fix in this list has a test that breaks. The one genuinely new, previously-uncaught class of bug (#6, the trigger API shape) is caught by testing against the real preload's call signature instead of an invented one — the actual root cause of why the last attempt's test suite missed it.

<!-- marvin:decisions -->
### sort-alts: Keep "Unblocks most" / "Priority" / "Oldest" / "Project" as the four sort options, these labels, as proposed? (optional)
- [ ] A: Yes, keep these four, these labels, as shown in the PR screenshots
- [ ] B: No — change the set and/or labels (say which, as a PR comment once you've seen the screenshots)

### no-priority-pill: A qualifying ticket has no p0–p3 label at all — how should its priority pill look? Shipping Option A as the default this round. (optional)
- [ ] A: Grey, no "Pn" prefix — just the kind text ("needs you" / "needs answer"), same style as P2/P3 (implemented)
- [ ] B: Grey, but show a literal placeholder (e.g. "—") before the kind text
- [ ] C: Something else (say what, as a PR comment)

## Task List

1. `dashboard/src/lib/needs_you_view.js`: rewrite. Export `PAGE_SIZE = 5`, `SORT_ORDERS = ['unblocks', 'priority', 'oldest', 'project']`. `paginate(rows, page, pageSize = PAGE_SIZE)` with garbage-input clamping. `sortRows(rows, order, boards = [])` — `'unblocks'` passthrough, `'priority'`/`'oldest'` as today but null/NaN-guarded, new `'project'` via `resolveProjectName`. `priorityPill(priority, kind)` — red/orange/grey, kind text, no-priority default. `resolveProjectName(row, boards)` via `projectIdOf` (imported from `../lib/projects.js`) matched against `board.repo`, falling back to `row.repo.split('/')[1]`. `readSortPref`/`writeSortPref` default `'unblocks'`. **Delete `applyRefresh`.** Tests #1–27 first.
2. `dashboard/test/needs_you_view.test.js`: rewrite fully for the new API (tests #1–27).
3. `dashboard/src/components/NeedsYouList.jsx`: fix the trigger subscription to the real preload shape (`window.api.triggers.on((t) => t.topic === 'activity' && load())`, single effect, `[]` deps, cleanup returned directly — mirroring `ProjectBoard.jsx:429`); store `rows` as the untouched canonical backend order (never overwrite with a sorted copy); derive `sortRows(rows, sortOrder, boards)` + `paginate(..., PAGE_SIZE)` at render time; pass `boards` straight into `resolveProjectName`/`sortRows` instead of the broken `{id,name}` reduction; fix empty-state copy to exactly `"Nothing needs you"`; update sort-button labels to the four `SORT_ORDERS` values with display labels ("Unblocks most", "Priority", "Oldest", "Project"); `priorityPill(row.priority, row.kind)`. Tests #28–33 first.
4. `dashboard/test/render_smoke.test.jsx`: replace test #24 with #34 and #35 (indexOf-ordering assertion, plus the negative case).
5. Confirm (read-only, no edit) that `dashboard/electron/main/relations_service.js` and `dashboard/electron/main/needs_you.js` remain unchanged — their existing tests (`relations_service.test.js` #8–12, `needs_you.test.js` #28–30) already guard the behaviour code review previously flagged there.
6. Run `cd dashboard && npm test` (vitest only — this is a pure dashboard/JS change; the issue's 14 of 19 `pytest`-timeout comments are unrelated full-repo infra noise, not this ticket's scope) until green.
7. Manual verification: launch the dashboard (`DeviceHub.app`/CDP per the simulator-screenshots rule), capture the three required screenshots — list populated (5+ rows, pagination visible), list empty ("Nothing needs you"), a ticket opened from a row — plus one showing the sort control with all four options, for Gil to confirm against the `sort-alts` decision. Confirm the chosen sort survives a relaunch and that a `needs-info`-only ticket shows in both the list and the home-card counts (already true via the untouched backend, but worth confirming end-to-end).
8. Open the PR with the `## Decisions` block above verbatim, the four screenshots, and a short note that the two backend files code review previously flagged needed no changes this round (confirmed by reading current source) and why — so Gil isn't asked to re-review a diff that doesn't exist.