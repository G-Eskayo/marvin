## North-star fit

**Reuses, no new files:**
- `dashboard/src/lib/saved_state.js: readSaved/writeSaved` — the exact localStorage-persistence pattern `MrReview.jsx` already uses for `collapsedSaved` (card collapse state, `COLLAPSED_KEY`). Dismiss state reuses this verbatim instead of inventing a second persistence mechanism.
- `dashboard/webhook-server/chat_helpers.js` (`helperStatus`, `describeHelper`, `listHelpers`, `sortHelpers` — exactly the functions the ticket's evidence cites at lines 20-24/71-79/86) — extended with one more pure, exported predicate (`crashExpired`) in the same style as the existing ones, not a new module.
- `dashboard/src/components/AgentsPanel.jsx: AgentCard` — extended with one optional prop (`onDismiss`) rather than forked into a second component. `AgentsPanel`'s own (Health tab) usage never passes it, so that surface is untouched.
- `dashboard/src/components/ChatHelpers.jsx` (the file the ticket cites at lines 14-21) is where the cap/dismiss/filter logic lands, as plain exported functions beside the existing `ChatHelpersView`/`ChatHelpers` — following `dashboard/src/lib/proposals_view.js`'s precedent of keeping view logic pure and separately testable, but *without* spinning it into its own `lib/` file, since (unlike proposals) there is only one consumer — "don't abstract for only two call sites."

**Simplest sufficient approach:** the two real problems are (a) `listHelpers()` never drops anything, so crashed cards accumulate forever (confirmed: `lib/chat_helpers.py`'s `KEEP=30`/`prune()` is a *disk* retention cap, unrelated to what's *shown*), and (b) `ChatHelpersView` renders the entire unbounded array with no per-card dismiss. Both are small, local fixes in the two files the ticket already points at — no redesign of the helper-log format, no new store, no Python changes needed, since "stays in the helper's history" is already true today (dismiss only has to stop *rendering* a card, never delete its JSON file).

**Token/compute cost:** zero new network/IPC calls, zero new files, no new test infra. Filtering is a pure comparison against data already computed by `describeHelper`.

**Phone-OS / reliability:** a home screen that silently grows to 60 permanent red cards is exactly the "something breaks silently" case north star 2 rules out; this makes the home screen trustworthy without adding any new always-on process.

**More capable, not more passive:** Gil doesn't have to remember to go clean these up or scroll past them — the UI stops lying about what's actually unresolved, while the underlying data (needed for debugging) is still on disk, untouched.

**Not followed literally — and why:** `CONTEXT.md:595-599` defines "Dismiss and mute" for the *live map / Vitals* "Worker" concept (`CONTEXT.md:538-548`). That system doesn't exist in code yet (confirmed: `docs/plans/dashboard-ux-potholes-2026-10-29.md:81` — "No Vitals code exists in the dashboard"). This ticket is scoped to today's `ActivityBoard` → `ChatHelpers` component, a different, already-shipped surface (`CONTEXT.md:1499-1512`). Building the map's general "recurs → marked 'seen before'" semantics here would be solving a problem that doesn't apply (each crash is a brand-new unique `agent_id`/file — see Tests #1 below — so there's no literal "recurrence of the same failure" to mark). I'm treating this as a reasonable scope call, not a contradiction of a recorded decision.

## Files read

- `lib/chat_helpers.py` (full) — hook writer, `KEEP=30`, `prune()`, `state_of` (confirms disk retention ≠ display cap)
- `dashboard/webhook-server/chat_helpers.js` (full) — `helperStatus`, `describeHelper`, `listHelpers`, `sortHelpers`
- `dashboard/electron/main/chat_helpers.js` (full) — `createHelpersReader`, `sanitize`, confirms remote Mac's data flows through `listHelpers()`'s `GET /helpers` route (`dashboard/webhook-server/index.js:202-205`) — so filtering once there covers local *and* remote-served data
- `dashboard/src/components/ChatHelpers.jsx` (full), `dashboard/src/components/AgentsPanel.jsx:1-140` (`AgentCard`, `Links`, `AgentsPanel`)
- `dashboard/src/components/ActivityBoard.jsx` (full) — confirms `ChatHelpers` still renders directly above the project boards today, matching the ticket's "render above the projects" description; W6.1 (#625) hasn't landed
- `dashboard/src/lib/saved_state.js` (full), its usage in `dashboard/src/components/MrReview.jsx:679,818` and `dashboard/src/lib/proposals_view.js` (full) — the reusable persistence/pure-logic patterns
- `dashboard/test/chat_helpers.test.jsx` (full) — existing coverage and the project's test style (no `testing-library`/`fireEvent` anywhere in `dashboard/test`; interactive/stateful glue is left untested, pure functions and `renderToStaticMarkup` markup carry all coverage)
- `lib/proposals.py` (full) — the only other "dismiss" implementation in the repo; confirms it's a different, heavier pattern (its own JSON store) not needed here
- `~/.agents/instance/docs/plans/dashboard-ux-potholes-2026-10-29.md` — the source plan item (W6.2) and its sibling W6.1 (#625, open, not yet built)
- `CONTEXT.md:530-604` ("Worker lifecycle on the map", "Dismiss and mute") and `CONTEXT.md:1499-1512` ("Chat helpers in Activity") — checked for conflicts (see north-star fit above)
- `docs/design/pipeline-g-eskayo-marvin-807.md` / `-807-tasks.md` — this pipeline's expected plan-doc format, followed below

## Decisions

None needed. The ticket already fixes the cap ("until then, 10") and the ticket's own wording scopes the fix to `crashed` ("Stopped unexpectedly") cards specifically, not `failed`. One judgment call, not escalated because existing precedent is unanimous: "persists across restarts" is implemented as per-viewer `localStorage` (like every other saved-UI-state in this codebase — `MrReview.jsx` collapse state, `MetricsPage.jsx`, `NeedsYouList.jsx`), not synced across the two Macs; no ticket text asks for cross-machine sync and nothing else in the dashboard does that for UI state.

## Tests (written first, in `dashboard/test/chat_helpers.test.jsx`)

**From "How we'll try to break it":**
1. *Crashes, restarts, crashes again* — two independent `helper-<id>.json` docs (different `agent_id`, same `chat` text) both end up `crashed`; dismissing the first's key (`machine:helper-a`) must not affect the second's visibility — `visibleHelpers` only hides the exact dismissed key.
2. *Clock skew between Macs* — `crashExpired(h, now)` where `now` is *before* the helper's recorded `finishedAt` (negative age): returns `false`, no throw — a backward clock jump never makes a card vanish.

**My additions (misuse categories the ticket's list didn't cover):**
3. Boundary: exactly `CRASH_EXPIRE_MS` old → not expired (`>`, not `>=`); `CRASH_EXPIRE_MS + 1` → expired.
4. `crashExpired` on a non-crashed helper (`running`/`failed`/`done`) always `false` — 24h rule never touches other states, confirming "failed" cards are out of this ticket's scope.
5. `listHelpers()` with a crashed helper doc whose transcript/timestamps are so old it's already past 24h → it's silently absent from the returned array (not just marked), exercised through the real `dir`-based test harness already used at `chat_helpers.test.jsx:70-82`.
6. `visibleHelpers`/`pruneDismissed` given `dismissed = null`, `undefined`, a string, or an array (malformed/hostile shape) — treated as "nothing dismissed," never throws.
7. `visibleHelpers` caps the home list at `HOME_CAP` (10): construct 3 `running` + 15 `crashed/done` → all 3 running are kept *plus* 7 others (never hides active work, even past the nominal cap), total other than running capped to fill the remaining slots.
8. `visibleHelpers` with more running helpers than the cap (e.g. 12 running) → all 12 stay, zero non-running shown; never silently drops something actively in flight.
9. `dismissKey` + `pruneDismissed`: dismissing a key that no longer appears in the current helper list (helper aged out or got pruned off disk between render and click — the race/stale-state case) is a no-op, and a stale dismissed entry is dropped the next time `pruneDismissed` runs against fresh data (garbage-collects itself, no manual cleanup, no unbounded `localStorage` growth).
10. A person's mistake — dismissing the same key twice (double-click) is idempotent: the resulting map has one entry, no duplicate/throw.
11. `ChatHelpersView` (via `renderToStaticMarkup`, matching the file's existing test style): a `crashed` card renders a `Dismiss` button; `running`/`done`/`failed` cards never do, even when `onDismiss` is supplied — confirms the button is status-gated, not just presence-of-callback-gated.
12. Regression guard: `AgentsPanel` (Health tab, `render_smoke.test.jsx:55-78`) still renders unchanged with no `Dismiss` text anywhere — `AgentCard`'s new prop is additive and opt-in.
13. Existing "nothing to show is nothing at all" test (`chat_helpers.test.jsx:189-192`) extended: a helper list that is non-empty but entirely dismissed and/or crash-expired also renders `''`, not an empty wrapper.

## Task List

1. In `dashboard/webhook-server/chat_helpers.js`: add `export const CRASH_EXPIRE_MS = 24 * 60 * 60 * 1000` and `export function crashExpired(h, now)`; filter it into `listHelpers()` (skip pushing an expired-crashed `h`). Covers Tests 1-5.
2. Write/run Tests 1-5 against the unmodified file first (confirm they fail), then make them pass with step 1.
3. In `dashboard/src/components/ChatHelpers.jsx`: add `export const HOME_CAP = 10`, `export const DISMISSED_KEY = 'chatHelpers.dismissed.v1'`, and pure exports `dismissKey(h)`, `visibleHelpers(helpers, dismissed, cap)`, `pruneDismissed(dismissed, helpers)`.
4. Write/run Tests 6-10 against step 3's pure functions.
5. Update `ChatHelpersView` to accept `dismissed`/`onDismiss` props, render `visibleHelpers(data?.helpers, dismissed)` instead of the raw array, and pass `onDismiss={h.status === 'crashed' && onDismiss ? () => onDismiss(dismissKey(h)) : undefined}` to each `AgentCard`. Adjust the early-return guard to check the post-filter list, not the raw one.
6. Write/run Tests 11, 13 (and re-run the existing chat_helpers.test.jsx suite) against step 5.
7. In `dashboard/src/components/AgentsPanel.jsx`: restructure `AgentCard`'s top-level `<button>` into a flex row with a sibling optional `Dismiss` `<button>` (no nested interactive elements), gated on `onDismiss` being passed, with `e.stopPropagation()` so it never toggles run-history or fires `onOpenTicket`/`onOpenMr`.
8. Run Test 12 (`render_smoke.test.jsx`) to confirm no regression on the Health tab's unrelated `AgentsPanel` usage.
9. In the default-exported `ChatHelpers`: read `dismissed` from `readSaved(window.localStorage, DISMISSED_KEY)` on mount; on each `data` refresh, run `pruneDismissed` and persist via `writeSaved` if it changed; add a `dismiss(key)` handler that merges the key in and persists; pass `dismissed`/`dismiss` down to `ChatHelpersView`.
10. Run the full `dashboard` test suite (`npm test` in `dashboard/`) to confirm no regressions elsewhere.
11. Manually exercise the dashboard (fixture/dev-mode path, as `#807`'s plan did) with a seeded 24h+-old crashed helper doc and a fresh one, confirm the old one is gone and the fresh one shows a working Dismiss button, then take and pin screenshots at 900px and 1440px per acceptance criterion 3, via `marvin-show`.
12. Open the PR with `Closes G-Eskayo/marvin#818`.