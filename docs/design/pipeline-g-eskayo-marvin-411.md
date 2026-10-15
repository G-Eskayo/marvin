## North-star fit

**Reuses before adding anything:** the ranked backend (`needs_you.js`'s `rankNeedsYou`, IPC `activity:needsYou`, preload `activity.needsYou`, `boards:list`) is untouched — correct, confirmed by reading `electron/preload/index.js:150,167` and `electron/main/index.js:349,426`. The saved-state pattern (`src/lib/saved_state.js`: `readSaved`/`writeSaved`/`ageText`) is proven in `MetricsPage.jsx` (`{report, error}` combined state, error always rendered next to data, `ageText`/`updating…` note) and is the one piece the previous attempt wrote about but never actually called — `NeedsYouList.jsx` currently has no `readSaved`/`writeSaved` import at all. The project-id↔repo mapping already has one canonical pure implementation, `src/lib/projects.js`'s `projectIdOf` — used by both `boards.js` (main) and now reusable by the renderer — so `project:<id>` resolution doesn't need a second implementation. `NextUpQueue.jsx`'s `{ state: null, error: null }` single-state-object pattern is the fix for the "error never shows" bug, not a new idiom.

**Correction to the previous plan's own fit claim:** it asserted the saved-state pattern was "reused verbatim." It wasn't — the shipped component skipped it entirely, which is exactly finding #1 below and the ticket's own requirement #5 ("no blank or spinner-first render"). It also asserted `resolveProjectFor(repo, boards)` satisfies the "`project:<id>` ticket shows under its project" acceptance criterion. It doesn't: `rankNeedsYou`'s row never carries the ticket's own labels, so there is nothing a renderer-side `resolveProjectFor(repo, ...)` could ever use to detect a `project:<id>` override — it can only ever match a board by the ticket's own fetch-repo, which is the *default* case, not the override case `boards.js`'s `loadBoard` already implements for the Project board page (`projectIdOf`, foreign-label partition, `electron/main/boards.js:170-270`). That acceptance criterion needs a small backend addition (next section), not just a renderer helper.

**Simplest sufficient approach:** keep all logic in the existing pure module `src/lib/needs_you_view.js` (`paginate`, `sortRows`, `readSort`/`writeSort`, `resolveProjectFor`, `priorityPill`, `kindLabel`), the component thin, matching the repo's own `usage_view.js`/`boot_view.js` convention. The one necessary backend addition — tagging each `rankNeedsYou` row with its resolved project id — reuses `projectIdOf` (already imported cross-boundary from `electron/main/boards.js:7`, so the same import from `electron/main/needs_you.js` is an established pattern, not a new one) instead of re-deriving the label-parsing logic that `loadBoard` already has.

**Token/time cost — this is the actual failure mode to fix:** three prior attempts (per the issue's own comment trail) timed out at 1200s; one more failed code review. The render tests this attempt writes (findings #4/#5) must do what `render_smoke.test.jsx` already proves is fast and correct for this repo: call `renderToStaticMarkup` once per case, synchronously, on the real component with real props/stubbed `window.api` — no `jsdom`, no fake timers, no `@testing-library` (not installed; confirmed in `package.json` — still true). The previous attempt's tests used `require()` inside an ESM vitest file and `Function.toString()` greps instead of this pattern; fixing that is also very likely what was timing/failing out in some of the six earlier attempts, independent of this specific code-review verdict.

**User impact:** unchanged from the prior plan's correct part — this surfaces, in one ranked place, tickets Gil currently has to notice by memory (the issue's own example: Seal Speak #406/#408/#410 went unseen). It surfaces work for a human decision; it doesn't decide anything for him. More capable, not more passive.

## Files read (every file this plan touches)

- `dashboard/electron/main/relations_service.js`, `needs_you.js`, `board.js`, `boards.js` (full `loadBoard`/`projectId` section), `src/lib/projects.js` — backend + the project:<id> re-filing logic it must now also reach
- `dashboard/src/components/NeedsYouList.jsx` (current, uncommitted — the file code review flagged)
- `dashboard/src/lib/needs_you_view.js` (current, uncommitted)
- `dashboard/test/needs_you_list.test.jsx`, `needs_you_view.test.js`, `relations_service.test.js`, `needs_you.test.js` (current, uncommitted + existing)
- `dashboard/src/components/ActivityBoard.jsx` (current, uncommitted — confirmed correct, no further change)
- `dashboard/src/components/DashboardHome.jsx` (loading-gate check, confirms sibling placement still right), `NextUpQueue.jsx` (the `{state, error}` pattern to copy), `MetricsPage.jsx` (the saved-state-first pattern to copy), `src/lib/saved_state.js`, `src/lib/ipcError.js`
- `dashboard/test/render_smoke.test.jsx` (the repo's actual render-test convention: real component, real/stubbed props, `renderToStaticMarkup`, assert on HTML)
- `dashboard/package.json`, `vitest.config.js` (confirmed again: no jsdom, no testing-library, esbuild automatic JSX)
- `docs/agents/decisions-format.md`, `CONTEXT.md` §"Needs You — Ranked list" (current, uncommitted)
- The issue's full comment trail (Gil's 2026-10-13 answers to all 5 open questions; the prior review verdict and six timeout/error comments)

This plan treats the uncommitted files already in this worktree as **the previous attempt's work to fix in place**, not a clean slate — same files, same tests, corrected.

## What the backend must actually gain (not previously planned)

`needs_you.js`'s `rankNeedsYou` must resolve each row's effective project the same way `loadBoard` does, so `resolveProjectFor` has something real to key on:

- In `rankNeedsYou`, for each ticket read its `project:<id>` label (if any), same string shape `loadBoard` already parses (`label.slice('project:'.length)`).
- Add `projectId: <that id, or projectIdOf(t.repo) if no such label>` to the row, importing `projectIdOf` from `../../src/lib/projects.js` (mirrors `boards.js:7`'s identical cross-boundary import — not a new pattern).
- The row's `repo`/the dependency graph (`blocksGraph`/`transitiveUnblocks`) stay keyed on the ticket's actual fetch-repo, unchanged — only *display* project resolution is affected. Relabeling the graph-grouping key would silently change "unblocks" counts across repos, which nothing in the ticket asked for.
- `resolveProjectFor(projectId, boards)` (renamed from `resolveProjectFor(repo, boards)`) then does `boards.find(b => projectIdOf(b.repo) === projectId)`, falling back to `{ id: projectId, repo: null, name: projectId }`-shaped data only if truly unmatched (unregistered/removed project — ticket's own "a person's mistakes" case).

## Tests to write FIRST

**Backend — `test/needs_you.test.js` additions** (new `projectId` field; must-fix finding #3's "confirm the board exposes what the renderer needs" concern, generalized to this real gap):
1. A ticket with no `project:<id>` label → `row.projectId === projectIdOf(t.repo)` (default case).
2. A ticket labeled `project:finance-os` in repo `G-Eskayo/marvin` → `row.projectId === 'finance-os'`, not `'marvin'` — the literal acceptance criterion ("a `project:<id>` ticket shows under its project").
3. A `project:<id>` label naming the ticket's own project (redundant self-label) → resolves to itself, not duplicated or dropped.
4. Multiple `project:` labels on one ticket (malformed/person's mistake) → the first one found wins deterministically, never throws.
5. A ticket with `labels: undefined`/`null` (malformed input) → falls back to `projectIdOf(t.repo)`, never throws.

**Backend — `test/relations_service.test.js` additions** (the "counts equal list length" criterion; `overview()`'s `needsYou` fix is already correct code, confirmed by reading `build()` — `b.tickets` is populated and carries `repo` — so these are regression tests, not bug fixes):
6. `overview()[repo].needsYou === rankNeedsYou(ticketsForThatRepo).length` exactly, for a mixed repo (`ready-for-human` + `needs-info` + `hold` + `pinned` + unrelated tickets).
7. A `needs-info`-only ticket (no `ready-for-human`) is counted — today's actual bug being fixed (`needs-info` lands in board column `backlog`, so the old column-based tally dropped it).
8. One repo's `getBoardData` throwing still leaves other repos' `needsYou` counts correct (mirrors the file's own existing "one repo failing" test, confirming `rankNeedsYou(b.tickets)` degrading gracefully through the existing per-repo try/catch in `build()`).
9. A repo with zero qualifying tickets → `needsYou: 0`, never `NaN`/`undefined`.

**Pure module `src/lib/needs_you_view.js`** — `test/needs_you_view.test.js` (rewritten, not patched — fixing must-fix finding #6 means the clamp tests must assert the clamp, not the stale `[]` behavior):

*Pagination (`paginate`)*:
10. 0 items → `{ rows: [], totalPages: 1 }` (an empty single "page", never `totalPages: 0`, so the UI never shows "page 1 of 0").
11. 5 items, pageSize 5 → 1 page, 5 rows.
12. 6 items, pageSize 5 → page 1 has 5, page 2 has 1, `totalPages === 2`.
13. 11 items, pageSize 5 → `totalPages === 3`.
14. **Fixes must-fix #6 directly:** a refresh shrinks the list from 11 to 5 items while a viewer sits on page 3 → `paginate(rows, { page: 3, pageSize: 5 })` returns page **1**'s rows (clamped to `totalPages`), not `[]`.
15. Page `0`, negative, or `NaN` → clamps to page 1.
16. `rows` is `null`/`undefined`/not an array → empty page, never throws.

*Sorting (`sortRows`)*: 17 identity order for `'unblocks'` (server ranking preserved) · 18 `'priority'` p0→p1→p2/p3→unprioritized, stable for ties · 19 `'age'` oldest-first, stable for ties (dropping the previous plan's untested `'project'` sort mode — the backend/UI only define `unblocks`/`priority`/`age`/`kind`, confirmed by reading both `needs_you_view.js` and the ticket's Gil-answer #4, which never mentions a project sort) · 20 `'kind'` needs-info-first · 21 unknown/corrupted sort key falls back to `'unblocks'`, never throws · 22 empty array for every mode → `[]`.

*Sort persistence*: 23 round-trips a chosen value · 24 `localStorage` throwing on read or write (quota/private window) degrades to default, never throws — `writeSort` currently has no guard at all (a real gap: `writeSort` wraps nothing in try/catch while `readSort` does) · 25 a corrupted stored value (non-JSON shape or a sort key removed from the valid set) is rejected back to default.

*Project resolution (`resolveProjectFor`, new signature: `(projectId, boards)`)*: 26 no match in `boards` (unregistered/removed project) → safe fallback object, never `"undefined"` reaching the DOM · 27 exact match → that board's `repo`/`name` · 28 `boards` missing/undefined/empty → same safe fallback, never throws.

*Priority pill / kind label*: 29 p0 red, p1 orange, p2/p3 grey · 30 `null`/missing priority → neutral fallback, never `undefined` · 31 malformed string (`'p9'`, `'P0'`) → same neutral fallback (defensive only — `needs_you.js`'s `getPriority` already guarantees `null | 'p0'..'p3'` via its own `/^p[0-3]$/` regex, confirmed by reading it, so this is a second line of defense, not patching a live bug) · 32 `kind: 'needs-info'` → "needs answer"-shaped label, `'ready-for-human'` → "needs you"-shaped label, unrecognized → safe default.

*Refresh-result reducer (`applyRefreshResult`)*: 33 success replaces values, clears prior error · 34 failure keeps previous values, records error · 35 **concurrency:** an older in-flight request's result landing after a newer one has already resolved is dropped (request-token check) — the double-click-Refresh / overlapping-trigger race.

**Component `src/components/NeedsYouList.jsx`** — `test/needs_you_list.test.jsx` (fully rewritten using `renderToStaticMarkup`, matching `render_smoke.test.jsx`'s and `MetricsPage`'s own convention — **no `require()`, no `.toString()` introspection, no fake async waiting**; every case below is a single synchronous render since `useState(() => readSaved(...))` seeds state before any effect runs, so saved-state-first is directly testable without jsdom or timers):

36. **Fixes must-fix #1 (hidden first-load failure):** `window.api.activity` entirely missing (stale preload) → first static render shows an explicit error line, not just "Loading…" forever. State must be `{rows: null, error: <msg>}`-shaped (mirroring `NextUpQueue`'s `{queue, error}`), with the loading branch rendering `error` whenever it's set, regardless of whether `rows` has resolved — this is the structural fix, and the test asserts the HTML contains the error text even though the fetch rejects synchronously before the effect's promise chain runs.
37. With a pre-seeded `localStorage` saved payload (`writeSaved` shape) and no API call made yet, the very first static render already contains a saved row's title — never "Loading…" when saved state exists. Direct test of the actual missing behavior from the previous attempt.
38. No saved payload, no data yet → first render shows a quiet one-line message, not a spinner graphic, not blank.
39. Rows resolved to `[]` (post-effect state passed as initial test state) → renders "Nothing needs you", not a hidden section.
40. **Fixes must-fix #2 (pagination reset):** given `page: 3` already in state and a *shorter* new `rows` array (simulating a poll/trigger refresh that shrank the list) passed through the same reducer path exercised by test 14's `paginate` clamp, the rendered page is clamped to the new last page, not silently reset to 1 and not stuck showing stale beyond-range content. Since this is a pure function of `(rows, page)` via `paginate`, this is tested by rendering with `page` state set to 3 and a 5-row `rows` array and asserting the page shown is clamped — the component must read the clamped page from `paginate`'s own `currentPage`, not hold a separately-reset `page` state.
41. Sort buttons render with the persisted sort choice already selected (reads `readSort()` synchronously on mount, no flash of the wrong button).

No test is written for "the fetch itself resolves and updates the DOM after mount" (that would need jsdom + real event loop ticks, the likely source of some of the six prior timeouts) — instead, every case above drives the component via its initial, synchronous state, exactly like `CompletedView`/`ProjectReadinessPanel`/`MetricsPage`'s existing tests do. The actual `onOpenTicket(repo, number)` click wiring stays untested glue, consistent with `NextUpQueue.jsx`'s identical, also-untested `onOpenTicket?.(r.repo, r.number)`.

**Not applicable, explicitly:** "wrong permissions"/"wrong machine" — local single-user main-process IPC, no new permission surface, matching the prior plan's (correct) call on this.

## Decisions

None. Every open question in the issue was answered by Gil's 2026-10-13 comment (row count/pagination, empty state, pill colours, sort default/options/persistence, saved-state behavior). The remaining judgment calls — sibling placement in `ActivityBoard.jsx` vs. nested in `DashboardHome` (confirmed correct: `DashboardHome` hard-blocks on its own `loading` state, line 142-145, which would contradict the ticket's own "no spinner-first render" requirement if `NeedsYouList` were nested inside it), the `resolveProjectFor` fallback shape for an unregistered project, and dropping the untested `'project'` sort mode that neither the backend nor Gil's answers define — are implementation details, not decisions for the owner.

## Task List

1. `electron/main/needs_you.js`: add `projectId` to each `rankNeedsYou` row (resolve `project:<id>` label via the same string parsing `boards.js` uses, default to `projectIdOf(t.repo)`, import `projectIdOf` from `../../src/lib/projects.js`) — write tests 1–5 first, then the change.
2. `electron/main/relations_service.js`: no code change (the `overview()` fix already present in this worktree is correct) — write tests 6–9 first to lock it in as a regression guard, confirming `pass` without touching the function.
3. `src/lib/needs_you_view.js`: fix `paginate`'s clamp behavior (test 14), add a try/catch guard to `writeSort` (test 24), change `resolveProjectFor`'s signature to take `projectId` instead of `repo` (tests 26–28), drop the unused `'project'` sort branch and the unused `applyRefreshResult`/`describeRow` exports that aren't wired into the component (confirm during step 4 whether either becomes genuinely needed; if not, remove — avoids the "unused" notes from the review) — write tests 10–35 first, then each change.
4. `src/components/NeedsYouList.jsx`: rewrite the data layer to a single `{rows, error}`-shaped state (mirroring `NextUpQueue.jsx`), wire `readSaved`/`writeSaved`/`ageText` for saved-state-first render (mirroring `MetricsPage.jsx`), remove the unconditional `setPage(1)` on every refresh and instead let `paginate`'s clamp (step 3) determine the shown page, render `error` whenever present regardless of `rows` — write tests 36–41 first, then the rewrite.
5. `test/needs_you_list.test.jsx` and `test/needs_you_view.test.js`: full rewrite per the "Tests to write FIRST" section — ESM `import`, no `require()`, assertions on real rendered/returned output, not `typeof`/`toString()` introspection.
6. `CONTEXT.md`: correct the existing uncommitted section — remove the unimplemented "Real time" and "sky blue" claims (still 60s-poll + saved-state-first, and the review's actual blue-950/300 token), and add the `project:<id>` resolution and the saved-state behavior now actually built.
7. Manual verification in the real running app (`run` skill or direct launch): screenshot the list populated, the empty "Nothing needs you" state, and a ticket opened from a row click — required by "Done when," not satisfied by unit tests.
8. Run `npm test` in `dashboard/` and confirm completion well under the pipeline's 1200s cap — all new tests are synchronous `renderToStaticMarkup`/pure-function calls, no timers, no jsdom.