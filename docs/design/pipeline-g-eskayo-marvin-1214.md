## North-star fit

**Reuses before adding anything new:**
- `next_step.js:prStep`'s existing `mine()` live/not-live split (used by every other PR `kind`) — the draft fix (bug 2) follows the same shape rather than inventing a new branch style.
- `WorkshopTab.jsx:useOpenItem` (line 309)'s `nav.at`-keyed state pattern — mirrored for a new `useProjectFilter`, instead of a new navigation primitive.
- `MrReview.jsx`'s `OpenPrs` component (lines 682-683, 787, 848): the exact `onCorrected` subscribe → filter-by-url → `<CorrectionNotice>` pattern already built for `MrDetail.jsx`, just not wired to `WorkshopItem.jsx` yet (that's M15's gap).
- `MrDetail.jsx:LinkedIssue` (exported) and `window.api.mr.ticketContext` (already a live IPC handler, `electron/main/index.js:1182`) — WorkshopItem.jsx simply never calls it (M18's gap, confirmed by reading the file: no `ticketContext` reference exists there).
- `ProjectBoard.jsx`'s `TagBar`/`OtherProjects` "clear"/chip styling — reused for the Workshop's new "filtered to project · clear" pill, so it reads like the rest of the app.
- `nav_history.js`'s own doc comment ("Pure and immutable... no React") — the new keyboard-history glue (`app_history.js`) follows the same pure-module shape so it's unit-testable without a DOM.
- `addon_not_set_up.test.jsx`'s hook-free `find()` + direct `.props.onClick()` call — the only existing precedent in this codebase for testing a click handler's argument without a DOM (no `@testing-library`/`react-test-renderer` dependency exists here; everything else is `renderToStaticMarkup` string assertions). Reused by extracting the one buggy button into a hook-free sub-component.

**Why this is the simplest sufficient approach:** every bug but #3 has a precise, already-demonstrated pattern elsewhere in the same file family; I'm extending those patterns in place rather than adding new abstractions. Bug #3 is the one place the ticket itself offers a scope-reducing escape hatch ("wire it in, or reopen ticket 756"), and I'm using it deliberately rather than guessing at a large, hardware-dependent feature a fresh attempt is likely to get wrong a third time.

**Tokens:** spent reading the five touched files plus their existing tests and one already-closed ticket (#756) up front, so the fix lands in one pass instead of iterating blind; saved by not re-deriving `describePrState`'s draft logic (already correct) or `nav_history.js`'s history math (already correct and tested) — only the wiring around them was missing.

**Phone-OS direction:** neutral; this is dashboard correctness, not new reach.

**Machine:** wherever the pipeline runs this ticket (dashboard-only change, no host-specific dependency).

**More capable or more passive:** more capable — it removes a dead link, an inflated/misleading count, and two silently-missing panes Gil currently has to go hunting for in MR Review instead.

One correction to the ticket's own framing: bug #4's footer currently points at **Health**, but the things it names (machines, helpers' health, the parallel toggle) live in **Activity** today (confirmed: `ParallelToggle` and `ChatHelpers` are rendered from `ActivityBoard.jsx`, not `HealthDashboard.jsx`), and per the lexicon's already-made 2026-11-09 decision they're moving to the Workshop itself. Since "Activity" would itself go stale the moment that move lands, I'm removing the line rather than correcting it to say "Activity" — the ticket explicitly allows either ("Remove or correct it").

## Tests first (one per bug, plus the break-it list)

1. **Dead MR Review link** (`dashboard/test/workshop_item.test.jsx`, new describe block for a new pure `mrLinkTarget(prKey)` in `lib/workshop_item.js`):
   - `"acme/app#5"` → `{ item: { repo: 'acme/app', pr: 5 } }` (unchanged single-PR case)
   - `"acme/app"` (bare repo) → `{ project: 'acme/app' }`
   - `undefined`, `null`, `''` → `{}` (today's dead-click case — must now mean "open Workshop, unfiltered", not "do nothing")
   - junk (`"#5"`, `123`, `"acme/app#x"`) → falls to the `project` branch or `{}`, never throws
   - New `dashboard/test/project_board.test.jsx`: extract `Column`'s "N waiting in MR Review →" button into a hook-free `MrReviewLink({count, repo, onOpenMr})`; test (via `find()` + direct `.props.onClick()`, the `addon_not_set_up.test.jsx` pattern) that it calls `onOpenMr('acme/app')`, never `onOpenMr()`; `count: 0` renders nothing.
   - `workshop_now.test.jsx` extension: a new pure `filterByProject(now, repo)` in `next_step.js` — keeps only that repo's items in every section, in order; unknown repo → all sections empty; `null`/`undefined` repo → passthrough, no-op.
   - `workshop_item.test.jsx` "deep links" extension: `nav = { tab: 'workshop', project: REPO, at: N }` renders Now filtered to `REPO`'s items only, with a "Filtered to … · clear" pill; items from another repo in the same feed don't appear.

2. **Drafts inflating Your move** (`workshop_now.test.jsx`): a plain idle draft PR (`pr(90, { isDraft: true })`) is never `yours`/"Look at it" — today it is (verified by reading `prState.js` + `next_step.js`: `describePrState` already returns `kind: 'draft'`, but `prStep` has no case for it and falls through to the generic `'Look at it'`/`yours` default). After the fix: idle draft → `waiting`/"Draft"; a draft whose ticket is live (`ctx.live` set) → `marvin`/"Building", following the same live/not-live split every other `kind` already uses via `mine()`.

3. **Back/forward dead** — see Decisions below; whichever option is chosen, the test is: new pure `app_history.js` (`historyKeyAction(e)`, `applyHistoryKey(action, history)`), no React:
   - ⌘[ / ⌘] recognized; plain `[`/`]` (no modifier, so typing isn't hijacked), ⌘+Shift+[, ⌘+Alt+[ all ignored
   - a sequence of `visit()`s then back/back/back: last one bounces (`null`), never crashes
   - forward after a back returns exactly the tab gone back from

4. **Workshop footer** (`workshop_now.test.jsx`): `render(feedOf(...))` no longer contains "Machines, helpers' health and the parallel toggle: Health." (simple negative assertion; this alone is the "test that fails before the fix").

5. **Item page gaps** (`workshop_item.test.jsx`, extending the `page()` helper to pass extra props and extending the `beforeEach` `window.api` mock with `mr.ticketContext: never`):
   - "Docs →" renders when `onOpenDocs` is supplied, calling `onOpenDocs(projectIdOf(repo))` — mirrors `MrDetail.jsx`'s own button
   - parent PRD: seeding `initial.context = { parent: { number, title, body } }` shows a "Design & Architecture (parent PRD)" section with that body; `parent: null` shows "Not available", not nothing
   - `notice` prop: `{ number: 9, url: pr(9).url, message: '…' }` on the matching PR shows "GitHub disagreed on #9"; a notice for a *different* PR's url is not shown

**Other misuse checked:** empty/huge feeds (already covered by existing `0 items and 200 items` test, extended to include a draft and a project filter), GitHub-unreachable (existing `as-of`/stale path untouched by these changes), malformed `prKey`/`nav.project` values (covered above), repeated clicks (idempotent — these are pure functions / `navigate` calls, no mutation), wrong machine/permissions (N/A, dashboard-only, no new privileged calls), stale state (filter clears correctly when `nav.at` advances without `project`, per `useOpenItem`'s existing pattern).

## Decisions
<!-- marvin:decisions -->
### nav-history-scope: How far should #1214 wire nav_history.js for bug 3 (back/forward dead)?
- [ ] A: Wire tab-level back/forward only (⌘[ / ⌘] switch between previously-active tabs, via nav_history.js exactly as built); reopen #756 for item-level history (which PR/doc was open within a tab) and the two-finger trackpad swipe, its edge-arrow animation, and the scroll/pinch exclusions — those need a real trackpad and a screen recording to verify, which this pipeline can't do, and is very likely why the last two automated attempts failed verification
- [ ] B: Reopen #756 entirely for bug 3; this PR only documents that nav_history.js is still dead code and attempts no wiring
- [ ] C: Attempt the full #756 scope now (item-level history + trackpad swipe + keyboard + animation + exclusions), accepting that this PR cannot verify the hardware-dependent parts headlessly

Recommendation: **A**. It's the only option that can satisfy this ticket's own acceptance criterion ("a test per bug that fails before the fix") for bug 3 — B ships no fix, so there's nothing to test; C repeats the likely cause of the last two failed verifications.

## Task List

1. `dashboard/src/lib/workshop_item.js`: add exported pure `mrLinkTarget(prKey)`; tests first.
2. `dashboard/src/App.jsx`: `openPrKey` calls `navigate('workshop', mrLinkTarget(prKey))` instead of its current regex-only, silently-failing logic.
3. `dashboard/src/components/ProjectBoard.jsx`: extract the Column "N waiting in MR Review →" button into a hook-free `MrReviewLink({count, repo, onOpenMr})` that calls `onOpenMr?.(repo)`; use it in place of the inline button (line 169). `WaitingOnYou`'s generic "MR Review →" (line 453-455) needs no code change — step 2 alone fixes it.
4. `dashboard/src/lib/next_step.js`: add exported pure `filterByProject(now, repo)`; tests first.
5. `dashboard/src/components/WorkshopTab.jsx`: add `useProjectFilter(nav)` (mirrors `useOpenItem`'s shape); apply `filterByProject` to the feed passed into `WorkshopNow`; render a "Filtered to `<project>` · clear" pill above it when active, styled like `ProjectBoard.jsx`'s `TagBar`/`OtherProjects`.
6. `dashboard/src/lib/next_step.js`: in `prStep`, add an explicit `kind === 'draft'` branch (live → `marvin`/"Building" with stuck-after-30-min, same as `mine()`'s logic; not live → `waiting`/"Draft"), placed before the generic decisions-check block. Tests first.
7. `dashboard/src/lib/app_history.js` (new): `historyKeyAction(e)`, `applyHistoryKey(action, history)`, pure, built on `nav_history.js`'s `back`/`forward`. Tests first.
8. `dashboard/src/App.jsx`: seed one `history` state with `startHistory({ tab: activeTab, item: null })`; every `navigate()`/`setActiveTab` call also `visit()`s it; a `keydown` window listener applies `app_history.js` to move `activeTab` (exactly like the existing tab-bar `onClick={() => setActiveTab(tab.id)}`, no `nav` touch).
9. `dashboard/src/components/WorkshopTab.jsx`: delete the footer line "Machines, helpers' health and the parallel toggle: Health." (line 302). Test first (negative assertion).
10. `dashboard/src/components/WorkshopItem.jsx`:
    - import `projectIdOf` from `../lib/projects.js`; add a "Docs →" button in the item-meta row calling `onOpenDocs?.(projectIdOf(repo))`.
    - add a `useRead`-based `contextRead` for `api.mr.ticketContext(ticketNumber, repo)` (seeded by `initial.context` in tests); render a `Card` "Design & Architecture (parent PRD)" using `LinkedIssue` (imported from `MrDetail.jsx`) when `ticketNumber != null`.
    - accept a `notice = null` prop; render `<CorrectionNotice notice={notice} onDismiss={...}/>` (imported from `MrReview.jsx`) when `pr && notice?.url === pr.url`.
    - Tests first for all three (extend `page()` test helper to pass extra props/`onOpenDocs`, and extend `beforeEach`'s `window.api.mr` mock with `ticketContext: never`).
11. `dashboard/src/components/WorkshopTab.jsx`: subscribe to `window.api.mr.onCorrected` exactly like `MrReview.jsx:OpenPrs` (lines 682-683), store `notice` in local state, pass it into `<WorkshopItem notice={notice} .../>`.
12. Run the full dashboard suite (`npm test` in `dashboard/`), then launch the app and capture screenshots for bugs 1, 2 and 5, including under 900 px, per the acceptance criteria — `marvin-show` them in the PR rather than a file card.
13. On landing: `gh issue reopen 756 --repo G-Eskayo/marvin` with a comment explaining the narrowed scope (tab-level history shipped in this PR; item-level history + trackpad swipe + animation + exclusions are what's left, and need a real trackpad + screen recording).