## North-star fit

**Reuses:** the ranked backend from #330/PR #371 (`rankNeedsYou`, IPC `activity:needsYou`, preload `activity.needsYou`, confirmed still wired at `dashboard/electron/main/index.js:410` and `preload/index.js:142`) — untouched. `DashboardHome.jsx` already renders `<NeedsYouList>` unconditionally above the project cards and `ActivityBoard.jsx` already forwards `onOpenTicket` — both correct, no changes needed. Reuses the established trigger+poll convention (`const off = window.api.triggers.on(...); return off` — see `ProjectBoard.jsx:429`, `DispatchStatusBadge.jsx:71`, `DocsExplorer.jsx:355`) instead of the dead `triggers.off` call currently in the tree. Reuses `projectIdOf` (`src/lib/projects.js`) and the `project:<id>` label-override convention already established in `boards.js:180-181` (byte-identical `label.slice('project:'.length)` pattern). Reuses the dashboard's existing `*-950`/`*-300` priority-badge shade convention (`ProjectBoard.jsx:49-52`: `bg-sky-950 text-sky-300`, `bg-orange-950 text-orange-300`, `bg-neutral-800 text-neutral-400`) instead of inventing new `-900/50` opacity shades.

**Simplest sufficient approach — the actual structural fix, corrected from both the current tree and the last design doc:** the working tree (uncommitted, left over from the attempt that failed verification) already has no reducer — `sort`/`page`/`rawRows` are already separate state, derived at render time via `sortRows`/`paginate`. So the last design doc's own diagnosis (kill the reducer) doesn't apply to what's actually on disk; it describes a fix that was *planned* but never *written*. The real remaining defect, found by reading `board.js`'s `deriveColumnCore` (board.js:93-140), is in `relations_service.js`'s `overview()`: `needs-info` tickets are classified into column `'backlog'`, not `'ready'` (board.js:137) — and `hold`/review/blocked/claimed states are decided *before* the `needs-info` check (board.js:101-136), so a `needs-info` ticket that also has an open PR lands in column `'review'`. `rankNeedsYou` ignores column entirely (board state + labels only). This means no column/owner heuristic over `cards` can ever be *provably* equal to `rankNeedsYou`'s own list — only calling `rankNeedsYou(b.tickets)` itself and grouping by repo can. That's simpler than the current parallel filter (no need to re-derive hold/pinned/done exclusion a second time) and removes an entire class of future drift — the drift this ticket exists to kill.

**Tokens:** spends a little fixing real bugs the last review's own notes implied but the tree never got (a dead-code `triggers.off` listener leak, a default sort that contradicts Gil's own answer, a hidden priority pill, wrong pill/kind copy); saves by deleting the `cards`-based `needsYou` heuristic rather than patching it further, and by not re-deriving ranking/graph logic a second time.

**Capability:** unchanged from the ticket's framing — surfaces tickets silently waiting on Gil (Seal Speak #406/#408/#410 went unseen); it surfaces, it doesn't decide for him. More capable, not more passive.

**Ticket's own fit claim:** none stated in the issue body.

## Why the last two attempts failed (read from the actual tree, not assumed)

The working tree already contains an implementation (uncommitted) that is further along than the prior design doc described — no reducer, derived sort/page — but it still has independent bugs the review evidently caught:

1. `NeedsYouList.jsx:67-70` subscribes via `window.api.triggers.on(handleTrigger)` then unsubscribes via `window.api.triggers.off?.(handleTrigger)` — **`triggers.off` does not exist** (`preload/index.js:144-151`: `on` *returns* the unsubscribe function; there is no `.off`). The `?.` swallows this silently, so the IPC listener is **never removed on unmount** — a real leak, and on every remount a duplicate listener double-fires `refresh()`.
2. Default sort state is `{ field: 'priority', direction: 'asc' }` (`NeedsYouList.jsx:10`), but Gil's answer #4 is explicit: *"Default is #330's ranking ('Unblocks most')."* `rankNeedsYou`'s own default order is unblocks-desc first (`needs_you.js:223-231`). This is a direct contradiction of an approved answer, not an implementation detail.
3. `priorityPill` (`needs_you_view.js:61-67`) returns `null` for a falsy/no priority, so rows with no `p0`-`p3` label show **no pill at all** — inconsistent with "a priority pill at the left of each row."
4. `kindLabel` returns `'Needs Info'` / `'Ready for Human'` (`needs_you_view.js:54-58`) — Gil's answer #3 specifies the pill must show **"needs answer"** / **"needs you"**, verbatim. Wrong copy, not a stand-in.
5. Empty state shows `"Nothing needs you right now."` (`NeedsYouList.jsx:107`) — Gil's approved copy (answer #2) is the exact line **"Nothing needs you"**.
6. `refresh()` unconditionally calls `setPage(0)` on every refresh (`NeedsYouList.jsx:43`), including the 60s poll and every `activity` trigger — this is the exact "pulled back to page 1 every minute" bug the prior review flagged, and it's still there.
7. `overview()`'s `needsYou` fix (`relations_service.js:103-117`) re-derives the needs-you rule over `cards`/columns and can disagree with `rankNeedsYou` on PR-linked `needs-info` tickets and stale-claimed `ready-for-human` tickets (see north-star-fit section above) — it is not provably equal to the list, which "counts equal list length" requires.
8. Sort-button click always starts a newly-clicked field at `'asc'` (`NeedsYouList.jsx:75-78`) — for "Unblocks" and "Age" this shows the least useful order on first click (fewest-unblocks-first, youngest-first).
9. No "Project" sort option exists, though Gil listed it as one of the alternatives to build (answer #4: "Priority, Oldest, Project").
10. `lastUpdated` is only set after a fresh network refresh resolves (`NeedsYouList.jsx:44`), never seeded from the cache's own `at` on mount — so the cache-first render (answer #5) shows cached rows with no "updated Xs ago" note until the first refresh completes, defeating the point of showing an age note at all.

None of these are in the prior design doc's "must-fix" list — they're new findings from reading the actual current files, which is why repeating that doc's plan verbatim would fail again.

## On the pytest regression (2→3 failed, tests_failed +1)

No Python file is touched by this ticket's diff (confirmed: `git diff --stat HEAD` touches only `dashboard/**`). I read `lib/test_change_rule.py`, `lib/tests/test_test_change_rule.py`, `lib/tests/test_commit_check.py` and `lib/tests/test_mutation_check.py` (the ADR 0063 gate tests, the most plausible candidates since they evaluate "code changed without a test changing") — all of them construct **isolated `tmp_path` git repos**, so they can't be perturbed by this worktree's actual diff. I could not execute pytest directly in this sandbox (Bash is denied outside read-only git/gh/graphify), so I can't name the specific failing test from here. Plan response: task 0 below runs the full pytest suite *before* any edit to capture the exact failing test names as a true baseline, and the final task re-runs and diffs by name — not just by count — so a regression is caught and attributed precisely rather than guessed at.

## Decisions

None. Every open question in the issue was answered in Gil's comment (rows/pagination = 5, paginated; empty state = exact copy "Nothing needs you"; pill = colour + kind text, exact wording given; sort control with four named options + persistence; cache-first load). The remaining calls (grey as the shared fallback for P2/P3 *and* no-priority rows, so every row has a pill; reusing the existing `*-950`/`*-300` shade convention instead of inventing one) fill an unstated edge case using the nearest already-approved rule, not new UI he hasn't approved — so no Decisions section per `docs/agents/decisions-format.md`.

## Tests to write first

No explicit "How we'll try to break it" section exists on this ticket (confirmed). Derived from Gil's "Tests to add" comment, the "Done when" bullets, every bug found above (each gets a named regression test), and standard misuse categories.

**0. Baseline:** run `npm test` in `dashboard/` and the full pytest suite, record current pass/fail by name, before touching anything.

**`dashboard/electron/main/needs_you.js` / `dashboard/test/needs_you.test.js`** (already covers project-label override cases 1-9 adequately — keep, no change needed there):
1. (misuse, not yet covered) a ticket with **no** `p0`-`p3` label still appears in the ranked list with `priority: null` (sort/pill fallback is a UI concern, not a ranking concern — regression guard that `rankNeedsYou` itself never assumed a priority exists)

**`dashboard/electron/main/relations_service.js` / `dashboard/test/relations_service.test.js`** (replace the current weak/dead tests 6 and 8 outright, keep 7/9/10's intent but make them exact):
2. **replaces dead test 6** (`expect(true).toBe(true)`): `overview()[repo].needsYou` equals `(await relations.needsYou()).filter(r => r.repo === repo).length` **exactly** (`toBe`, not truthy), for a fixture mixing `needs-info`, `ready-for-human`, `hold`, `pinned`, and closed tickets
3. a **closed** ticket still labelled `needs-info` is not counted (regression for the review's archived/closed-cards finding — `[...c.cards, ...(c.archive || [])]` includes closed tickets)
4. a `needs-info` ticket that **also has an open PR** (column would be `'review'` under the old cards-heuristic) is still counted, because `rankNeedsYou` doesn't look at column — proves the cards/column approach could never be exact and the `rankNeedsYou`-reuse fix is required, not optional
5. **replaces weak test 8** (`toBeGreaterThanOrEqual`): exact count (`toBe`) for three `needs-info` tickets, one of which is `hold`
6. (misuse) one repo's `getBoardData` rejecting still lets another repo's `needs-info`/`ready-for-human` tickets count and list correctly (matches the existing `try/catch` per-repo isolation at `relations_service.js:33-35`)

**`dashboard/src/lib/needs_you_view.js` / new/extended `dashboard/test/needs_you_view.test.js`:**

*`sortRows`*
7. `'unblocks'` desc is the field's meaningful order (more unblocks first) — used to assert the *default* sort elsewhere, not just that the comparator works
8. `'priority'` asc: P0 → P1 → P2/P3 → null, stable for ties
9. a malformed priority value (`'px'`, `''`, non-string, missing) never throws and never produces a non-deterministic position — assert total order preserved (no row lost/duplicated) for mixed-garbage input
10. `'project'` field (new): alphabetical asc/desc by `row.project`
11. empty array in → empty array out, for every field; does not mutate the input array
12. unknown/garbage field returns rows unchanged, never throws

*`paginate`* (already solid — keep, add):
13. a page value valid before a refresh shrank `rows` is clamped automatically on the next call (proves dropping `setPage(0)` from `refresh()` is safe — the shrink case is handled here, not by resetting page)
14. 0/5/6/11 items (Gil's named pagination edges)
15. non-numeric page (`NaN`, string, `undefined`), 0/negative `pageSize` never throw or return an empty page incorrectly

*`kindLabel`* (fix wording)
16. `kindLabel('needs-info')` → `'needs answer'`, `kindLabel('ready-for-human')` → `'needs you'` (Gil's exact copy, not the current "Needs Info"/"Ready for Human")
17. unknown/garbage kind → `''`, never throws

*`priorityPill`* (fix fallback + colours)
18. `p0` → red, `p1` → orange, `p2`/`p3` → grey, **using the `*-950`/`*-300` shade family already in `ProjectBoard.jsx`**, not new ones
19. `null`/missing/garbage priority (`'p9'`, `'P0'` uppercase, `''`) → the **same grey fallback as P2/P3**, never `null`/hidden

*`loadSort`/`saveSort`*
20. default when nothing saved is `{ field: 'unblocks', direction: 'desc' }` (regression for bug #2 above — not `'priority'`/`'asc'`)
21. round-trips through fake storage; missing key / corrupted JSON / unknown field → the same default
22. `storage.getItem` throwing (privacy mode) and `storage.setItem` throwing (quota) are both swallowed independently

*`loadCachedRows`/`saveCachedRows`* (`{rows, at}` shape, already implemented — keep, add):
23. corrupted JSON / wrong shape (`rows` not an array, missing/non-numeric `at`) → `null`, never throws
24. a huge payload (500 rows) round-trips without choking
25. `storage` exceptions on either call are swallowed

**`dashboard/src/components/NeedsYouList.jsx` / `dashboard/test/render_smoke.test.jsx`** (SSR/no-jsdom, consistent with repo convention):
26. **regression for the trigger-leak bug:** the value returned by a stubbed `window.api.triggers.on` is the thing called on unmount — structurally assert the cleanup function returned by the mount effect is `window.api.triggers.on`'s own return value, not a call to a separate `.off` method (prove the component uses the `const off = ...on(...); return off` convention, not `triggers.off?.()`)
27. **regression for the page-reset bug:** `refresh()` never calls `setPage` — behavioral check: trigger two successive `needsYou()` resolutions with the user already on page 1, assert the rendered page stays on page 1 (not reset to 0) when the row count after refresh still supports that page
28. **regression for the default-sort bug:** with no saved preference, the first render's effective sort is `unblocks`/`desc` (not `priority`/`asc`)
29. a saved sort preference (`{field:'age', direction:'asc'}`) is used verbatim on hydration, including when the cache's rows are empty (sort state is independent of row count)
30. **regression for the empty-pill bug:** a row with no priority label still renders a (grey) pill, never an empty slot
31. **regression for the kind/empty-copy bugs:** rendered output contains "needs answer"/"needs you" (never "Needs Info"/"Ready for Human"), and the empty state renders exactly "Nothing needs you" (not "...right now.")
32. **regression for lastUpdated-from-cache:** with a populated `{rows, at}` cache and no resolved refresh yet, the "updated Xs ago" note renders immediately using `at`, not only after the network call resolves
33. when `window.api.activity.needsYou()` rejects, the previously-cached rows still render, with the error/age note alongside them, not instead of them
34. `renderToStaticMarkup(<NeedsYouList .../>)` renders without throwing with no `window`/`localStorage` (SSR has none)
35. a ticket title containing `<script>`/`<img onerror>` renders as literal escaped text (default JSX escaping, no `dangerouslySetInnerHTML`)
36. `DashboardHome`'s existing loading-state test and the "renders unconditionally above project cards" tests still pass (regression guard — no reshuffle needed there, confirmed correct already)

## Task List

1. Run `npm test` (vitest) in `dashboard/` and the full pytest suite now, before any edit; record pass/fail by test name as the true baseline (task 0 above).
2. `dashboard/electron/main/relations_service.js`: replace `overview()`'s `cards`/column-based `needsYou` heuristic with `rankNeedsYou(b.tickets)` grouped and counted by `repo` (same function `needsYou()` already calls at line 131) — provably exact by construction, simpler than re-deriving hold/pinned/done exclusion a second time. Revert the now-unneeded `labels: card.labels || []` addition to the `cards.set(...)` call (line 30) since nothing will consume it after this change. Replace tests 6/8 with tests 2, 3, 5 above; add tests 4 and 6.
3. Confirm `dashboard/electron/main/needs_you.js`'s `project:<id>` label override (already correct from the current tree) needs no change; add misuse test 1.
4. Rewrite `dashboard/src/lib/needs_you_view.js`: add `'project'` to `sortRows`; harden the `'priority'` comparator against malformed values; fix `kindLabel` to return `'needs answer'`/`'needs you'`; fix `priorityPill` to always return a pill (grey fallback for null/unknown, matching P2/P3), using the `*-950`/`*-300` shade family from `ProjectBoard.jsx`; change `loadSort`'s default to `{field:'unblocks', direction:'desc'}`. Write tests 7-25.
5. Rewrite `dashboard/src/components/NeedsYouList.jsx`: (a) fix the trigger subscription to capture and call the function `triggers.on` returns, deleting the dead `triggers.off?.()` call; (b) seed `sort` default from the fixed `loadSort` (now `unblocks`/`desc`); (c) seed `lastUpdated` from the cache's `at` (converted via `new Date(cached.at).toISOString()`) on mount, not only after a live refresh resolves; (d) remove `setPage(0)` from `refresh()`, relying on `paginate`'s own clamping for a page that outlives a shrinking row set; (e) give each sort field its own sensible first-click direction (`priority`→asc, `unblocks`→desc, `age`→desc, `project`→asc) instead of always starting at asc; (f) add the fourth "Project" sort button, rename the "Age" button label to "Oldest"; (g) fix the empty-state copy to the exact line "Nothing needs you". Write tests 26-35.
6. Run `npm test` in `dashboard/`, fix fallout; add test 36 regression checks.
7. Re-run the full pytest suite; diff failing test names against the task-1 baseline (not just the count) — if a genuinely new failure appears, trace and fix its root cause (not a filter/workaround) before proceeding.
8. Launch the dashboard (DeviceHub/Electron) and capture the three required screenshots for the PR: list populated (showing all four sort options and both pill colours), list empty ("Nothing needs you"), and a ticket opened from a row — plus a manual check that the project-card and "Waiting on you" strip counts match the list length for a project with a `needs-info` ticket that is also `hold`-labelled (must now be excluded from both).