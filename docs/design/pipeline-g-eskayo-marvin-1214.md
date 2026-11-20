## North-star fit

**Reuses, before adding anything new:**
- Bug 2 (drafts): the exact `mine()`-after-`sent-back` pattern already in `prStep` (`next_step.js:130`) — `mine(live ? … : …)` vs a plain `step('nobody', …, 'waiting')` — no new mechanism.
- Bug 5 (item-page gaps): `MrDetail.jsx`'s already-built, already-wired pieces — `LinkedIssue` (the "parent PRD" block, `MrDetail.jsx:331-339`), `CorrectionNotice` (`MrReview.jsx:657`), the `window.api.mr.ticketContext` / `window.api.mr.onCorrected` / `window.api.relations.context` IPC bridges (all already in `preload/index.js`), and `projectIdOf` (`lib/projects.js`) — all proven, all zero backend changes, just wiring them into `WorkshopItem.jsx` the way `MrDetail.jsx` and `ProjectBoard.jsx`'s `TicketDrilldown` already do.
- Bug 3 (nav history): `nav_history.js`'s own already-tested API (`nav_history.test.js` already demonstrates tab-level + item-level screens), and `image_zoom.js`'s `viewerKey(e)` convention (skip the shortcut when `e.target.tagName` is `INPUT/TEXTAREA/SELECT`) for the new keyboard handler.
- Bug 1 (dead link): App.jsx's existing `openPrKey`/`navigate` plumbing; no new IPC, no new nav shape beyond what `nav.repo` already means for the Activity tab.

**Simplest sufficient approach:** every fix is a frontend-only change (`dashboard/src/**`); nothing in `webhook-server`, `electron/main`, or Python needs to move, because the data each gap needs already exists and is already exposed over IPC — the bugs are all "nobody wired it here yet," not "it doesn't exist yet."

**Where this spends vs. saves tokens:** small, surgical diffs (one function, one prop, one line) rather than a rewrite; the one place I deliberately do **not** build the full fix (bug 3's two-finger swipe + per-item history) is exactly where building it would cost a lot (a cross-cutting refactor across 5 components) for a result I cannot verify (ticket #756's own acceptance bar requires a live trackpad and a screen recording — impossible in this headless run).

**User impact:** fixes 1, 2, 4, 5 remove false signals (a dead link, an inflated "Your move" count, a wrong tab name, missing context) — strictly more capable, no new passivity. Bug 3's partial fix (keyboard ⌘[/⌘] tab-back/forward) is a real, if smaller, capability; the owner decides below whether that's enough for now.

## Decisions

```markdown
## Decisions
<!-- marvin:decisions -->
### navscope: Back/forward wiring (bug 3) — how far to go now?
- [ ] A: Wire tab-level back/forward now (⌘[ / ⌘], via `nav_history.js`), reopen #756 for the two-finger swipe gesture, its edge-follow animation, per-item (not just per-tab) history, and the live-trackpad + screen-recording check #756's own acceptance bar requires — none of which this headless run can build safely or verify.
- [ ] B: Attempt the full swipe-gesture + per-item history build now anyway, knowing it ships without the live-trackpad verification #756 itself demands.
```

I've built **A** as the default (see Task List) since it's the only option I can actually verify headlessly; **B** stays available if the owner wants to risk it unverified.

## Tests first

**Bug 1 — dead `onOpenMr?.()` link**
- New pure dispatcher `mrLinkTarget(key)` (`lib/mr_link.js`), unit-tested: `"repo#42"` → `{kind:'pr',...}`; bare `"owner/repo"` → `{kind:'project',...}`; `undefined`/`''`/junk (`"not-a-repo!!"`)/a non-numeric PR (`"o/r#abc"`) → `{kind:'all'}` (today's silent no-op, made explicit); a huge-but-valid string resolves correctly without hanging (regex safety).
- `filterSections(sections, repo)` (`lib/next_step.js`), unit-tested: keeps only `type==='pr' && repo===filter` per section; `repo=null` → unchanged; a repo with nothing open → every section empty, no throw; 500-PR fixture → still correct (huge input).
- `WorkshopNow` with a `filterRepo` prop: shows only that project's PR rows across sections; shows a "Clear filter" banner; no filter → today's behavior unchanged.

**Bug 2 — drafts inflating "Your move"**
- `prStep` on a bare `{repo, number, isDraft: true}` (no mergeQueue, no decisions): section `'waiting'`, owner `'nobody'`, not `'yours'`.
- Same PR with `ctx.live` set (MARVIN building its ticket): section `'marvin'`.
- Regression guard: a PR that is `isDraft: true` **and** `sentBack: true`, or **and** has pending decisions/failing checks, still gets its real (`sent-back`/`decisions-pending`/`checks-failed`) treatment, not swallowed into the new draft branch (describePrState only emits `kind:'draft'` when nothing else is wrong — this proves `prStep` honors that).

**Bug 3 — nav_history never imported**
- New pure `keyboardNavAction(e)` (`lib/nav_history.js`, reusing `image_zoom.js`'s `viewerKey` shape): `{key:'[',metaKey:true}`→`'back'`, `{key:']',metaKey:true}`→`'forward'`; no `metaKey` → `null`; an unrelated Cmd-combo (`{key:'s',metaKey:true}`) → `null` (must never hijack Cmd+S/Cmd+C etc.); typing in an `INPUT`/`TEXTAREA`/`SELECT` → `null` even with the right keys.
- Integration-style test combining `keyboardNavAction` + `visit`/`back`/`forward`: repeated ⌘[ past the start bounces (`edge:'start'`) without throwing, matching `nav_history.test.js`'s existing "nothing left" behavior.

**Bug 4 — stale footer**
- `WorkshopNow` render no longer contains `"parallel toggle: Health."`; contains the corrected text naming Activity.

**Bug 5 — item-page gaps**
- `WorkshopItem` ticket-body rendering: given a ticket body mentioning `ADR 0033` and a `relations.context` stub returning `{adrs:{33:'docs/adr/0033-x.md'}}`, the body renders it as a link (today: plain text, because `ctx={{repo}}` carries no `adrs`) — this is the concrete, testable face of "never reads the linked ticket's context."
- Given `window.api.mr.ticketContext` resolving `{ticket, parent:{number,title,body}}`, the page shows a "Design & Architecture (parent PRD)" card with the parent's title; given `parent: null`, shows "Not available," not a crash.
- A "Docs →" button is present and calls `onOpenDocs(projectIdOf(repo))`.
- Given `window.api.mr.onCorrected` fires `{repo,number,url,message}` matching the open PR's `url`, a `CorrectionNotice` ("GitHub disagreed…") renders; a notice for a **different** PR's `url` does not render on this page (must not bleed across items).

## Task List

1. `lib/next_step.js`: add the draft branch to `prStep` (reusing `mine()`); export `filterSections(sections, repo)`.
2. `lib/mr_link.js` (new): export `mrLinkTarget(key)`.
3. `lib/nav_history.js`: add `keyboardNavAction(e)`, mirroring `image_zoom.js`'s typing-guard.
4. `test/workshop_now.test.jsx`: add the bug-2 (`prStep` draft), bug-1 (`filterSections`, `WorkshopNow filterRepo`), and bug-4 (footer text) tests above.
5. `test/mr_link.test.js` (new): the `mrLinkTarget` tests above.
6. `test/nav_history.test.js`: add the `keyboardNavAction` tests above.
7. `test/workshop_item.test.jsx`: add the bug-5 tests above (extend the `beforeEach` API stub with `relations.context`, `mr.ticketContext`, `mr.onCorrected`).
8. `components/ProjectBoard.jsx`: Column's "N waiting in MR Review →" button calls `onOpenMr?.(repo)` instead of `onOpenMr?.()` (`:169`); leave `WaitingOnYou`'s cross-project "MR Review →" (`:453`) calling with no argument — it has no single project in scope, so it now resolves to "open Workshop, unfiltered" via `mrLinkTarget`.
9. `App.jsx`: route `openPrKey` through `mrLinkTarget` (`'pr'`→open item, `'project'`→`navigate('workshop',{repo})`, `'all'`→`navigate('workshop')`); add tab-level history state (`startHistory`/`visit`) over `activeTab`, and a `keydown` listener calling `keyboardNavAction` → `back`/`forward` → `setActiveTab`.
10. `components/WorkshopTab.jsx`: fix the footer sentence (bug 4); derive `filterRepo` from `nav.repo` (only when no item target and not dismissed) and pass it + a clear callback into `WorkshopNow`; render the "Showing <project>'s PRs · Clear" banner inside `WorkshopNow`.
11. `components/WorkshopItem.jsx`: fetch real `ctx` via `relations.context(projectIdOf(repo))` and thread it into `TicketCard`'s `IssueBody` calls (parent PRD's ADR/doc links); add the "Docs →" button next to the item title; add the "Design & Architecture (parent PRD)" card (`LinkedIssue`, reusing `MrDetail.jsx`'s export) gated on `ticketNumber != null`; add local `notice` state via `window.api.mr.onCorrected`, rendering `CorrectionNotice` (reusing `MrReview.jsx`'s export) when it matches the open PR.
12. Screenshots for bugs 1, 2 and 5 (including under 900 px), per the ticket's acceptance criteria.
13. PR body: state plainly that bug 3 ships option A only (tab-level ⌘[/⌘]), and open/point at a reopened #756 for the swipe gesture + per-item history + its live-trackpad verification.