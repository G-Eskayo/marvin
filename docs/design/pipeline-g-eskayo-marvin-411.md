## North-star fit

**Reuses before adding anything new:** the ranking engine (`needs_you.js: rankNeedsYou`, `missingFor`, `transitiveUnblocks`) is untouched and still the single source of truth. `relations_service.js`'s `overview()` already derives `needsYou` from `rankNeedsYou` grouped by repo (lines 111–121 of the current worktree) — that part of the previous attempt is correct and stays. New code reuses `DashboardHome.jsx`'s `formatRelativeTime`, `ProjectBoard.jsx`'s `REFRESH_MS`/`triggers.on('activity', …)` convention, `prefs.js`'s per-field type-checked default-merge pattern (for the state file), and — the piece the last attempt missed — `NextUpQueue.jsx`'s **exported pure row-describer** (`describeQueueRow`, tested directly with `toMatchObject`, no rendering). That is the actual established convention for testing a fetch-backed list component in this codebase, and it's what the placebo tests should have been.

**Simplest sufficient approach:** no new abstraction layer. `needs_you_view.js` stays the one small pure-logic module (`paginate`, `sortRows`, `pillFor`, plus a new `describeNeedsYouRow`); `needs_you_state.js` stays the one small disk-state module; `NeedsYouList.jsx` stays the one component. I'm not introducing a presentational/container split — this codebase has zero precedent for that, and it would be premature machinery for one call site (Colton check: the underlying principle here is "pull logic into pure functions," not "split components").

**Where it spends/saves tokens:** saves — reuses the ranking engine and the already-correct `overview()` fix instead of re-deriving either; the disk cache still removes a live `gh`-backed computation from the hot path, per #236. Spends — fixing the four must-fix defects plus the real bugs the review also surfaced as notes, because shipping with known races, dead persisted state, and unapproved colours would just bounce a third time.

**Ticket's own stated fit:** the issue has no north-star-fit section to check.

**More capable or more passive:** unchanged from the first design — Gil still decides every item; the feature ranks and surfaces, never answers for him.

**Correction to the prior attempt's own stated fit:** that doc claimed the pill reuses `bg-red-950 text-red-300` / `bg-orange-950 text-orange-300` / `bg-neutral-800 text-neutral-400` and that sort keys are `unblocks/priority/oldest/project`. Neither is true of the code that was actually written (`needs_you_view.js` uses invented `bg-red-900`/`bg-orange-900`/`bg-yellow-800` and sort keys `null/priority/age/unblocks`, confirmed by reading the file directly). This revision makes the code match what the doc already (correctly) promised.

## What went wrong, and the fix, file by file

1. **`dashboard/test/NeedsYouList.test.js`** — tests 24–30 assert `true === true` / `typeof fn === 'function'` and never import `NeedsYouList`. Fix: delete them. Replace with (a) a real SSR smoke test of the container matching this repo's actual convention for fetch-backed components (`TicketAgentsPanel`/`ProfilesPanel`: renders nothing before the effect runs — `toBe('')`), and (b) real, direct unit tests of the new `describeNeedsYouRow` pure function (the `NextUpQueue`/`describeQueueRow` pattern), which is where the actual row content, pairing, and pill logic now live and can be asserted without rendering at all.

2. **Race on mount (`NeedsYouList.jsx`)** — `loadCached()` and `refresh()` run concurrently; if cached resolves after fresh, it clobbers fresh data. Fix: a `freshLoadedRef` guard — `refresh()` sets it before calling `setRows`; `loadCached()` checks it before applying the cached rows. Extracted as a one-line pure predicate `shouldApplyCachedRows({ freshLoaded })` in `needs_you_view.js` so the exact condition is unit-tested without simulating React effect timing (which this codebase has no harness for).

3. **Sync write that can throw (`index.js:422` today, really `needs_you_state.js`)** — fix belongs in the state module, not the IPC handler: `index.js` has zero existing unit tests (it's the Electron entrypoint; nothing in this repo unit-tests `ipcMain.handle` wiring directly), so a guarantee placed there is unverifiable by this repo's own conventions. `writeNeedsYouState` becomes best-effort: it catches its own `mkdirSync`/`writeFileSync` errors and never throws. Tested with a real filesystem failure (a path component that's an existing file, forcing `ENOTDIR`), not a mock.

4. **Sort persistence is dead (`needsYouSort` never read/written, `needsYouState()` doesn't return it, `NeedsYouList` never calls `setNeedsYouSort`)** — fix: the state file's shape grows to `{ rows, at, sort }`; `readNeedsYouState` always returns a fully-defaulted object (mirrors `prefs.js`'s per-field type check, never returns `null`); `writeNeedsYouState` becomes a **merge**-write (read-current, shallow-merge the given fields, write back) so a sort-only write can't drop cached `rows`, and a rows-only write can't drop a previously-chosen `sort`. `index.js`'s `activity:needsYouSort` handler now actually persists (`writeNeedsYouState(path, { sort })`) instead of assigning a local variable nobody reads; the dead `let needsYouSort` is deleted. `NeedsYouList` initializes its `sort` state from the loaded cached state, and its sort control calls `window.api.activity.setNeedsYouSort(key)`.

Also fixed while touching this code (real bugs the review flagged as notes, not re-litigated as new "Decisions" — none of them contradict anything Gil approved):
- Priority pill colours switched to the dashboard's existing tokens (`bg-red-950 text-red-300`, `bg-orange-950 text-orange-300`, `bg-neutral-800 text-neutral-400` for p2/p3/missing) and now carry the kind label ("needs answer" / "needs you"), per Gil's comment #3 — this was simply not built.
- Sort keys renamed/extended to `unblocks` (default) / `priority` / `oldest` / `project`, matching Gil's comment #4 exactly (the old `age`/`null` keys are gone; an unknown/legacy key falls back to `unblocks`).
- `parseInt(priority[1])` → `parseInt(priority.slice(1), 10)` with a `Number.isFinite` guard (fixes `p10` parsing as `1`, and NaN on malformed values).
- Page size fixed to 5 (Gil: "show 5, then paginate, pages of 5") with clamping for negative/non-integer/past-the-end pages.
- `setPage(0)` no longer runs on every background refresh/poll — only on an explicit sort change — so a person on page 2 isn't yanked back every 60s.
- Unblocks list items render `#N title` (via `describeNeedsYouRow`), never a bare `#N` — the same house rule `Related.jsx` already enforces, and the same bug existed for the row's own items list.
- `row.unblocks.items.length` → `row.unblocks?.items?.length` guard against a shaped-but-incomplete row.
- `rows` initial state becomes `null` ("not loaded yet") instead of `[]`, so "loaded and genuinely empty" and "not loaded yet" are no longer conflated — required to implement Gil's "updated Xs ago / updating / updating failed" note correctly, since that note must never show before anything has loaded.

## Decisions

None. Every open question in the ticket was already answered by Gil in his 2026-10-13 comment, and nothing in this revision needs a new owner choice — the fixes above are implementation corrections against requirements he already approved (sort persistence, existing colour tokens, pagination size), not new product decisions. The "project sort = alphabetical by repo short name" reading is the only free parameter Gil didn't spell out, and it's not decision-worthy: there is no other sensible reading of "a Project sort option" and getting it wrong costs nothing to fix later.

## Tests first

**`needs_you_state.js`** (extends `dashboard/test/needs_you_state.test.js`, real filesystem via `mkdtempSync`, mirrors `prefs.js`'s merge-default pattern):
1. Missing file → `{ rows: [], at: null, sort: null }`.
2. Corrupt/non-JSON file → same default.
3. Per-field bad types (`sort: 123`, `rows: "x"`, `at: "100"`) → that field defaults, others unaffected if valid (mirrors `prefs.js`).
4. Write `{ rows, at }` then read → round-trips, `sort` stays `null` (not clobbered to some other default).
5. Write `{ rows, at }`, then write `{ sort: 'priority' }` → read returns all three fields merged; reverse order also preserves both.
6. `writeNeedsYouState` creates parent directories that don't exist yet.
7. `rows: []` persists and reads back as `[]`, not dropped as falsy.
8. A 500-row array round-trips without truncation.
9. Two sequential writes leave the file valid JSON, last-write-wins (documents the synchronous single-process guarantee — true concurrent writers don't exist in this process model).
10. **(regression test for must-fix #3)** Writing to a path whose parent segment is an existing file (not a directory, forcing `ENOTDIR`) does not throw, and a subsequent write to a valid path still succeeds afterward — the module recovers rather than staying wedged.

**`needs_you_view.js`** (extends `dashboard/test/needs_you_view.test.js`):
11–15. `paginate(rows, page, 5)`: 0, 5, 6, 11 items → correct page counts/slices at the pageSize-5 edges Gil asked for.
16. A page past the last page clamps to the last valid page.
17. A negative/non-integer page clamps to page 0 (never throws).
18. `sortRows` for all four keys (`unblocks`, `priority`, `oldest`, `project`) produces the documented order; `project` groups by repo short name ascending.
19. An unknown/legacy saved sort key (`null`, `'age'`, a corrupted string) falls back to `unblocks`.
20. `sortRows` does not mutate its input array.
21. `pillFor(row)`: p0→red token, p1→orange token, p2/p3/missing/malformed (`'p10'`, `'px'`)→grey token, never throws; kind `needs-info`→"needs answer", `ready-for-human`→"needs you".
22. **(regression test for must-fix #2)** `shouldApplyCachedRows({ freshLoaded: true })` → `false`; `shouldApplyCachedRows({ freshLoaded: false })` → `true` — the exact race condition, pinned as a pure predicate.
23. **(regression test for the bare-number bug)** `describeNeedsYouRow(row)` with a row whose `unblocks.items` includes `{ number, title }` entries produces a label that pairs every number with its title — never a bare `#N` — for both the row itself and each unblocked item.
24. `describeNeedsYouRow` on a row with `unblocks: { count: 2 }` and no `items` array does not throw (optional-chaining guard).
25. `describeNeedsYouRow` on a row whose `title` contains `"><script>` or an `onerror=` payload returns it as a plain string field (the escaping guarantee is then provable at render time in test 27, since `describeNeedsYouRow` never produces HTML, only data).

**Component smoke test** (extends `dashboard/test/render_smoke.test.jsx`'s `renderToStaticMarkup` convention, matching `TicketAgentsPanel`/`ProfilesPanel`):
26. `NeedsYouList` renders nothing before its effect runs (`toBe('')`) — proves it doesn't crash with `window.api` unset during SSR, the same guarantee every other fetch-backed component in this file carries.
27. **(regression test for the XSS note, at the real render boundary)** build a static row list directly (bypassing the fetch) by rendering the JSX the way the row loop does — reuse `describeNeedsYouRow`'s output in a tiny inline JSX snippet the way `Related.jsx`'s test does for `rel.tickets` — and assert a `"><script>` title appears escaped as text, never as a tag, matching the pattern `render_smoke.test.jsx` already uses for `Related`.

**`relations_service.js`** (extends `dashboard/test/relations_service.test.js`, already has tests 10–13 for label/hold/pinned/repo-separation; adding):
28. `overview()[repo].needsYou === rankNeedsYou(tickets).filter(r => r.repo === repo).length` for a mixed set of `ready-for-human` + `needs-info` + `hold` + `pinned` tickets — the acceptance criterion, verbatim and pinned exactly rather than only indirectly covered.
29. A ticket physically in one repo but labelled `project:<id>` for another shows up under that other project's `needsYou` count, not its home repo's — confirms the existing cross-repo relabeling in `relations_service.build()` (`tickets.push({ ...i, repo })`) already satisfies this acceptance criterion; written as a regression test since nothing currently exercises this angle for `needsYou` specifically.

## Task List

1. `dashboard/electron/main/needs_you_state.js` — change `readNeedsYouState` to always return a fully-defaulted `{ rows, at, sort }` object (never `null`, per-field type check mirroring `prefs.js`); change `writeNeedsYouState` to merge-write (read-current, shallow-merge, write) and to swallow its own `mkdirSync`/`writeFileSync` errors (best-effort, never throws). Tests 1–10 first.
2. `dashboard/src/lib/needs_you_view.js` — rewrite `pillFor` to take the row (existing colour tokens + kind label), rewrite `sortRows` to the four real keys with safe fallback and the `parseInt` fix, change `paginate`'s default pageSize to 5 with clamping, add `shouldApplyCachedRows` and `describeNeedsYouRow`. Tests 11–25 first.
3. `dashboard/electron/main/index.js` — delete the dead `let needsYouSort` variable; `activity:needsYouSort` now calls `writeNeedsYouState(path, { sort })`; `activity:needsYou`'s success path calls the same merge-write with `{ rows, at: Date.now() }`.
4. `dashboard/electron/preload/index.js` — no change (the three IPC bridges already exist and match the new contract).
5. `dashboard/src/components/NeedsYouList.jsx` — rewrite: `rows` initial state `null`; load cached state once on mount (apply only if `shouldApplyCachedRows` says so, and seed `sort` from the cached value); `refresh()` sets the fresh-loaded ref before `setRows`; drop `setPage(0)` from the background-poll/trigger path, keep it only on an explicit sort change; render loop maps `rows.map(describeNeedsYouRow)`; render an "updating…" / "updated {formatRelativeTime(at)}" / "updating failed, showing data from {formatRelativeTime(at)}" note per Gil's spec, never a blocking spinner; sort control calls `window.api.activity.setNeedsYouSort(key)`. Test 26 first.
6. `dashboard/test/NeedsYouList.test.js` — delete tests 24–30 (placebo); replace with test 26 and the escaping check in test 27.
7. `dashboard/test/relations_service.test.js` — add tests 28–29.
8. Run `npm test` in `dashboard/` and fix any regressions.
9. Launch the real app, capture screenshots for the PR: list populated (with pills, ask, unblocks, "updated Xs ago"), list empty ("Nothing needs you"), a ticket opened from a row, and the sort control with all four options — required by "Done when" and the house rule that any look-changing work carries images.