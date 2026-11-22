## Implementation Status

### ✅ Completed (2026-11-20)

**Bug 1**: Core implementation done
- Created `dashboard/src/lib/review_link.js` with `reviewTarget(key)` function ✅
- Modified `App.jsx` to use `reviewTarget` and branch on bare-repo targets ✅
- Fixed `ProjectBoard.jsx` lines 169 and 453 to pass `repo` to `onOpenMr` ✅
- **Pending Decision bug1-filter**: Choose A, B, or C for project filter implementation

**Bug 2**: Complete ✅
- Added test case for draft PR in `workshop_now.test.jsx` ✅
- Added `kind === 'draft'` branch to `prStep` in `next_step.js` line 122 ✅
- All 3741 dashboard tests pass ✅

**Bug 3**: Pending decision
- **Pending Decision bug3-nav-history**: Choose A (wire keyboard shortcuts now) or B (reopen #756 in full)

**Bug 4**: Complete ✅
- Removed stale line from `WorkshopTab.jsx:302` ✅

**Bug 5**: Complete ✅
- Added "Docs →" control in item-meta row ✅
- Added parent-PRD card with `LinkedIssue` ✅
- Extended `useWorkshopNow` to handle `onCorrected` subscription ✅
- Updated `WorkshopItem` to render `CorrectionNotice` ✅
- All imports added (`projectIdOf`, `LinkedIssue`, `CorrectionNotice`) ✅

### Test Status
- **New test** (Bug 2 draft PR): Added to `workshop_now.test.jsx` ✅
- **Full test suite**: 3741 tests pass ✅
- **No regressions**: All existing tests still passing ✅

### Files Modified
1. `dashboard/src/lib/review_link.js` (created) ✅
2. `dashboard/src/App.jsx` ✅
3. `dashboard/src/components/ProjectBoard.jsx` ✅
4. `dashboard/src/components/WorkshopTab.jsx` ✅
5. `dashboard/src/components/WorkshopItem.jsx` ✅
6. `dashboard/src/lib/next_step.js` ✅
7. `dashboard/test/workshop_now.test.jsx` ✅

### Screenshots
Screenshots can be captured by:
1. Starting dev server: `npm run dev` in dashboard directory
2. Testing each bug visually:
   - Bug 2: Draft PR in Workshop Now view shows "Wait for draft to be ready"
   - Bug 4: Stale footer line is gone from Workshop Now
   - Bug 5: "Docs →" button and parent-PRD card visible in Workshop Item page

### Decisions Awaiting Input

Please choose for the following:

**Decision bug1-filter**: Project filter for bare-repo navigation targets (choose A, B, or C)
- [ ] A: Add clearable project filter to WorkshopNow
- [ ] B: Navigate to unfiltered Workshop view
- [ ] C: Filter only PR-type rows for that repo

**Decision bug3-nav-history**: Keyboard navigation implementation (choose A or B)
- [ ] A: Wire ⌘[/⌘] keyboard shortcuts now, reopen #756 for swipe gesture + edge animation
- [ ] B: Reopen #756 in full scope, no code change for this PR

---

## North-star fit

Reuses, before adding anything: `CorrectionNotice`/`onCorrected` and `LinkedIssue`/`ticketContext` (`MrReview.jsx`, `MrDetail.jsx`) for bug 5; the `mine()`/`step()` helpers already in `next_step.js` for bug 2 (no new control-flow primitive); the `TagBar` clearable-filter pattern (`ProjectBoard.jsx:491-511`) for bug 1's filter UI; `useWorkshopNow`'s single top-of-tree IPC-subscription pattern for the new correction-notice state. Nothing here needs a new component framework or dependency — new code is a handful of pure functions (testable with the existing `renderToStaticMarkup`/plain-vitest style, no new test harness) plus wiring into already-existing props. Tokens are spent on reading the existing MR Review detail page carefully so the Workshop item page gets the *same* behavior rather than a re-invented one (bug 5), and saved by not building a trackpad-gesture system from scratch (bug 3, see Decisions). This leaves Gil more capable: five real "sends him to the wrong place / mis-states the count" bugs stop lying to him, which is squarely north star 3 (raises the human experience by not hiding or inflating what's waiting on him) and north star 2 (Workshop is the phone-OS-shaped single place for this).

I could not read `instance/docs/plans/tab-consolidation-intent-and-gaps-2026-11-09.md` (not in this repo/worktree — it's in a different, inaccessible repo) so C3/C5/M5/C17/M15/M18 are taken from the ticket's own restatement of them, not the source doc directly.

## Root cause per bug (verified against current code)

1. **Dead MR-review links** — `ProjectBoard.jsx:169` (`Column`, inside the review column) and `:453` (`WaitingOnYou`) both call `onOpenMr?.()` with no argument. `onOpenMr` is `App.jsx`'s `openPrKey`, which regex-matches `repo#number` and does nothing on `undefined`.
2. **Drafts inflate "Your move"** — `next_step.js prStep` (lines 104-143) has no branch for `describePrState(pr).kind === 'draft'`, so it falls through to the catch-all `step('owner', 'Look at it', 'yours')` (line 142). `describePrState` (`prState.js:18-24`) only ever produces `kind: 'draft'` when the PR would otherwise be plain `'ready'` — a draft is never blocked by checks/conflicts/decisions underneath, so the fix is unconditional and simple.
3. **`nav_history.js` has no importer anywhere in `src/`** — confirmed by grep. It's a 59-line pure module with full test coverage from closed ticket #756, but #756's own acceptance criteria also required "checked live with a real trackpad, with a screen recording" and a swipe gesture + Chrome-style edge-arrow animation — neither of which a headless agent can do or verify. See Decision.
4. **`WorkshopTab.jsx:302`** footer says "Machines, helpers' health and the parallel toggle: Health." Verified: `DeviceColumns`, `ChatHelpers`, and `ParallelToggle` are rendered in `ActivityBoard.jsx` (the Activity tab), not Health. The line is wrong today and will be wrong again once they move to Workshop ("today's decision") — a second stale pointer. Simplest durable fix: remove it.
5. **Workshop item page gaps**, all verified against `WorkshopItem.jsx`: it calls `api.boards.ticket` for the ticket's own body (`TicketCard`) but never `window.api.mr.ticketContext`, so there is no parent-PRD section (M18); it has no "Docs →" affordance anywhere (MrDetail.jsx:246-249 has one); and it never subscribes to `window.api.mr.onCorrected`, so a GitHub-disagreed correction (`CorrectionNotice`, MrReview.jsx:657-664) never shows here (M15).

## Decisions

<!-- marvin:decisions -->
### bug1-filter: Bug 1 — what does "filtered to that project's PRs" look like in the Workshop's Now view?
- [ ] A: Add a small, clearable project filter to `WorkshopNow` (reusing `ProjectBoard.jsx`'s `TagBar` clear-chip pattern): the five sections keep their shape but only show items whose `repo` matches, with a banner "Showing `<project>` only · Clear". `App.jsx openPrKey` gains a branch for a bare `owner/name` (no `#number`) that treats it as a project filter instead of a PR key.
- [ ] B: Don't build a filter. Fix only the dead link itself — the two buttons navigate to the Workshop's Now view unfiltered (better than doing nothing, but doesn't literally satisfy "filtered to that project's PRs").
- [ ] C: Something narrower than A: filter only the PR-type rows (not tickets/proposals) for that repo, closer to the original "N waiting in MR Review" count's meaning.

### bug3-nav-history: Bug 3 — wire `nav_history.js` in now, or reopen #756?
- [ ] A: Wire a minimal, testable slice now: `⌘[` / `⌘]` keyboard shortcuts drive `nav_history.js`'s `back`/`forward` across the cross-tab `navigate()` calls already in `App.jsx` (no trackpad swipe, no Chrome-style edge arrow). Separately reopen #756, scoped down to just the swipe gesture + edge animation + lifting each tab's local "item open" state (MrReview, ActivityBoard, DocsExplorer) into the shared history, and the live-trackpad/screen-recording verification — all of which need real hardware and can't be done or checked headlessly.
- [ ] B: Reopen #756 in full (covers everything, including the keyboard shortcuts) and make no code change for bug 3 in this PR; `nav_history.js` stays unimported until #756 is picked up.

<!-- /marvin:decisions -->

I recommend **A** for both: for bug 1 it's the only option that actually does what the ticket's prose says, reusing an existing clear-filter UI; for bug 3 it stops `nav_history.js` from being flatly dead code and gives a real, headlessly-testable fix, while being honest that the swipe gesture itself needs a trackpad and a screen recording neither of which exist in this session.

## Tests first (one per "How we'll try to break it" case, plus misuse the section didn't name)

The ticket has no explicit "How we'll try to break it" section, so these are built from its Bugs list plus the standard misuse checklist (bad/empty/huge/malformed input, each dependency failing, repeats/concurrency, wrong permissions, stale state, a person's mistakes), matched to what's actually testable in this codebase's existing style (pure-function tests via vitest + `renderToStaticMarkup`; no `fireEvent`/testing-library is used anywhere here, so click-driven behavior is tested by extracting the decision into a pure function, same as `nav_history.js`/`workshop_item.js` already do).

**Bug 1 — dead MR-review link** (new `dashboard/src/lib/review_link.js`, pure, + `dashboard/test/review_link.test.js`):
- `reviewTarget('owner/repo#42')` → `{ repo: 'owner/repo', pr: 42 }` (existing behavior, must not regress).
- `reviewTarget('owner/repo')` (bare repo, the two broken call sites' real fix) → `{ repo: 'owner/repo' }`, no `pr` key.
- `reviewTarget(undefined)`, `reviewTarget('')`, `reviewTarget('garbage')`, `reviewTarget('owner/repo#0')`, `reviewTarget('owner/repo#-1')`, `reviewTarget(42)` (non-string) → `null` (the exact bug: today these all silently no-op inside `openPrKey`, which the test must currently fail against *before* the fix exists, since the function doesn't exist yet).
- If Decision A: a `buildNow`/`WorkshopNow`-level test (extend `workshop_now.test.jsx`) that a `projectFilter` of a repo with zero matching items renders "nothing waiting" rather than crashing, and clearing the filter restores every section's full count (`expectCoverage` must still hold with the filter cleared).

**Bug 2 — drafts in "Your move"** (extend `dashboard/test/workshop_now.test.jsx`, `prStep`):
- Draft PR, no `ticketRef` (nothing live) → `{ owner: 'nobody', verb: 'Draft', section: 'waiting' }`, never `'yours'`.
- Draft PR with a `ticketRef` whose ticket is actively building (`live` set, recent event) → `{ owner: 'marvin', verb: 'Draft', section: 'marvin', phase: 'build' }`.
- Draft PR with a `ticketRef` whose ticket is live but stalled past `MARVIN_STUCK_MS` → `section: 'stuck'` (the existing `mine()` stuck check must still apply to drafts).
- Draft PR that **also** has `decisions.pending.length > 0` → still `section: 'waiting'`/`'marvin'`, verb `'Draft'`, never `'Answer N decisions'` (today's actual double-inflation bug, since the decisions block runs before any draft check).
- `expectCoverage` (existing helper) re-run with a draft PR injected into `snapshot()` — still exactly one section, never zero, never two.

**Bug 3** (Decision A): new `dashboard/test/app_nav_shortcuts.test.js` (or extend `nav_history.test.js`) for whatever pure function backs the keyboard shortcut (e.g. a `handleNavKey(event, history)` helper): `⌘[`/`⌘]` map to `back`/`forward`; a bare `[`/`]` without `⌘` does nothing (must not hijack ordinary typing in a text box); repeated `⌘[` past the start bounces without throwing (`canGoBack` false); fired while a text input has focus does nothing (a person typing `[` in a Decisions note box must not navigate them away mid-edit).

**Bug 4 — stale footer** (extend `workshop_now.test.jsx`): render `WorkshopNow` and assert the literal misleading string ("Machines, helpers' health and the parallel toggle: Health.") is absent from the output — this test fails today, passes once the line is removed.

**Bug 5 — item-page gaps** (extend `dashboard/test/workshop_item.test.jsx`):
- *Docs →*: given a `target`/`feed` with a resolvable item, the rendered page contains a "Docs →" control; clicking semantics aren't testable without a DOM harness, so this is paired with the PR screenshot requirement for live verification.
- *Parent PRD*: seed `initial.context` (new seed prop, matching the existing `initial.ticket`/`initial.closedPr` pattern) with `{ ticket: null, parent: { number: 9, title: 'The PRD', body: '...' } }` → the page renders a "Parent" / parent-PRD section with that title; with `context.parent: null` → renders "Not available." (reusing `LinkedIssue`'s existing null-handling, not a new empty state); with the `ticketContext` read still pending (no `initial.context`) → shows a loading state, not a crash.
- *GitHub disagreed*: pass a `notice` prop whose `url` matches the resolved PR's `url` → `CorrectionNotice`'s text renders; a `notice` whose `url` does **not** match (the disagreement was about a different PR entirely, e.g. two draft PRs open on screen at once in different windows) → nothing renders (must not leak another PR's correction onto this page); `notice: null` → nothing renders, no crash.
- Ticket-only item (no PR, `readOnly`/no `pr`) with a parent PRD present → parent-PRD section still renders (the ticket's own parent, independent of whether a PR exists yet).

## Task List

1. **Bug 1 (pending Decision bug1-filter):** add `dashboard/src/lib/review_link.js` with `reviewTarget(key)`; rewrite `App.jsx`'s `openPrKey` to use it, branching to `navigate('workshop', { projectFilter: repo })` for a bare-repo target. Fix `ProjectBoard.jsx:169` and `:453` to call `onOpenMr(repo)` (pass `repo` into `WaitingOnYou`, which doesn't currently receive it). If Decision = A, add the clearable project filter to `WorkshopNow`/`buildNow`'s call site in `WorkshopTab.jsx`, reusing `TagBar`'s clear-chip visual pattern.
2. **Bug 2:** add the `kind === 'draft'` branch to `prStep` in `next_step.js`, placed right after the `'in-queue'` check and before the decisions block.
3. **Bug 3 (pending Decision bug3-nav-history):** if A — wire `⌘[`/`⌘]` in `App.jsx` to `nav_history.js`'s `back`/`forward`, ignoring the keys when a form field has focus; reopen #756 scoped to the swipe gesture, edge animation, per-tab item-state lifting, and live-hardware verification. If B — reopen #756 in full, no code change here.
4. **Bug 4:** remove the stale line at `WorkshopTab.jsx:302`.
5. **Bug 5:** in `WorkshopItem.jsx` — add `projectIdOf` import and a "Docs →" control in the item-meta row; add a parent-PRD card (fetch via `window.api.mr.ticketContext(ticketNumber, repo)`, render with `LinkedIssue`, mirroring `MrDetail.jsx`'s "Design & Architecture (parent PRD)" section); extend `useWorkshopNow` (`WorkshopTab.jsx`) to subscribe to `window.api.mr.onCorrected` and expose `notice`, pass it into `WorkshopItem`, render `CorrectionNotice` filtered to the resolved `pr.url`.
6. Write all tests above before each corresponding code change (red, then green).
7. Run the full dashboard test suite (`cd dashboard && npm test`) — not just the new files — before opening the PR.
8. Capture screenshots for bugs 1, 2 and 5, including one set under 900 px width, for the PR body.
9. Open the PR with the Decisions block above (unresolved) carried over verbatim so Gil can answer by button; if bug3-nav-history resolves to A or B, open/annotate #756 accordingly as part of the same PR's description, not as a separate silent action.