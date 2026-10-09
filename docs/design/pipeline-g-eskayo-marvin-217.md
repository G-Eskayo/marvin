## North-star fit

**Reuses:** everything already built and verified by the prior attempt (PR #368, commit `28d186d`) — `webhook-server/ticket_stages.js` (`readStages`, project-keyed by #216), the `isLiveNow`/`taskIsTicket` liveness pattern already used in `activity.js`'s ticket list (not the claim label — directly answers the #161 regression), `webhook-server/failure.js`'s `RULES`/`REMEDIATION_BY_CODE`, and the existing dashboard screenshot tool (`dashboard/scripts/capture_screenshot.mjs`). No new stage-log writer, no new liveness signal, no new screenshot pipeline — this ticket only adds a *reader/view* over data and machinery that already exist. `deriveSegments` stays a dependency-free pure function (stage-log JSON in, segment array out) so MARVIN Mobile can reuse it verbatim later, per the issue's own stated reuse intent — verified true by reading the code, not just asserted.

**Simplest sufficient approach:** keep the two touch-points in the hot files (`index.js`, `mr_review.js`) to the smallest possible diff — one new trailing option each, no restructuring — because those two files are exactly where every one of this PR's four straight rejections failed (see below), and every other ticket landing nearby (#341 added `autoMergeShadow` while #368 sat open) touches the same two lines. New logic goes in new files (`stage_strip.js`, `StageStrip.jsx`) that nothing else can collide with.

**Token cost:** spends tokens once re-deriving the integration against current `main` (the stale `28d186d` patch cannot be reapplied verbatim — `mr_review.js`'s options signature already moved since it branched); saves tokens everywhere else by carrying over the already-tested design instead of re-deriving it from scratch, and by fixing the four real content gaps below instead of debugging a four-times-rejected diff blind.

**More capable, not more passive:** Gil asked for this because a hung ticket is invisible today ("if it is hung for 5 hours I want that obvious to me"). A correct strip shortens incident response from log archaeology to a glance — this doesn't do Gil's job for him, it gives him the fact he's missing to do it himself.

## Why the last four attempts failed, and what that changes here

PR #368's actual feature diff (isolated against its true merge-base `ceba4b9`, not the stale comparison the UI shows) is small and was already verification-passed (+18 tests, 0 regressions). GitHub's repeated "conflicts in `dashboard/electron/main/index.js`, `dashboard/electron/main/mr_review.js`" was caused by drift, not by a defect in the feature itself:

- `index.js`: the only line #368 touched is the options object literal passed to `listPipelinePrs(...)` inside the `mr:list` handler. Ticket #341 (auto-merge shadow, merged while #368 sat open) added `autoMergeShadow: getAutoMergeShadow` to that exact same literal. Textbook same-line conflict.
- `mr_review.js`: #368 added `stagesDir`/`liveDispatch` to `listPipelinePrs`'s destructured options *and* to the returned object literal. #341 added `autoMergeShadow` to both of those same two spots in between.

Current `main` already has `autoMergeShadow` baked into both signatures (confirmed by reading `mr_review.js:233` and `index.js:596` directly). **This attempt must be written fresh against current `main`'s signatures**, not reapplied from the old patch — cherry-picking/rebasing the literal diff is what the automated rebase bot already tried four times and failed at.

Reading PR #368's actual content (not just its test pass/fail) also surfaced four real gaps worth fixing now rather than carrying forward, since this is a from-scratch rewrite anyway:

1. **"Skipped stages greyed" is unmet.** `deriveSegments` does `if (!event) continue` — a stage with no event yet is omitted from the array entirely, not rendered as a grey dot. The issue's own example (`gate · → merge ·`) and AC2 both require future/skipped stages to *appear*, dimmed. No existing test catches this because every fixture only supplies stages that already have events.
2. **Hover tooltip drops `machine` and `cost_usd`.** `deriveSegments` computes both on every segment, but `StageStrip.jsx`'s `title=` string never includes them, even though the requirement ("hovering a stage shows its time, machine and cost") and the composed segment data both exist. The tooltip only interpolates `timestamp`, `message`, `remediation`.
3. **`mutation` stage is missing from the dashboard's stage vocabulary.** `webhook-server/ticket_stages.js` (`VALID_STAGES`) and the Python mirror (`~/.agents/lib/ticket_stages.py`) both include `mutation` (ADR 0063's mutation-testing gate, #339) between `gate` and `merging`. `stage_strip.js`'s `VALID_STAGES_ORDERED`/`STAGE_LABEL` omit it — any ticket whose stage log has reached mutation testing would silently drop that stage from the strip, which breaks "works for every onboarded project" since mutation testing is a real, generic pipeline stage, not a MARVIN-only one.
4. **Click opens the whole PR/ticket detail, not "its events, with times."** Gil's comment literally asks to click *a stage* and see *its events* (plural — a stage can have several: `started` → `failed` → retried `started` → `passed`, all collapsed by `latestPerStage` before `deriveSegments` ever sees them). `onStageClick` in #368 just calls `onSelect(pr)`, which opens `MrDetail`/ticket detail generically — no per-stage breakdown, and the retried-attempt history is already lost by the time it reaches the component.
5. (Minor, same bucket as #4) `deriveSegments`'s `extractRefusalLabel` has three dead entries (`NOT_MERGEABLE`, `CI_FAILED`, plus `WRONG_BASE`/`SENT_BACK`/`CI_PENDING` which only relabel to the already-default `'Merging'`) — only `OUT_OF_ORDER → 'Order check'` is ever reachable, because `recordApproveError` only writes the `refused <CODE>:` prefix for the six `REFUSAL_CODES` and only `OUT_OF_ORDER` gets a distinct label. Keep the mapping but drop the dead entries so a future reader doesn't trust them.

## What to build

**New files** (no conflict risk, carry over the proven design from #368, fixed for gaps 1–4):

- `dashboard/src/lib/stage_strip.js` — `deriveSegments(stages, { rebase, isLiveNow, now, stallMinutes = 30 })`. Changes from #368's version:
  - Walk `VALID_STAGES_ORDERED` (now including `mutation`) and emit a segment for *every* stage up to and including the furthest one with any event — stages with no event get `status: 'pending'` (the existing grey/`·` styling already defined in `StageStrip.jsx` but never reached). Stop emitting pending segments after `done`/a terminal failure, so a finished ticket doesn't trail eight grey dots forever.
  - Keep the `refused <CODE>:` vs `<CODE>:` detail-parsing (verified correct against real writer: `refusal_log.js:38` and `merge.js`'s inline `stage(...)` calls), but trim `REMEDIATION_BY_CODE`'s label map to only the reachable `OUT_OF_ORDER → 'Order check'` entry (gap 5).
  - Each segment keeps `events: [...]` — the *full* per-stage event list (not just latest), sourced from a new parameter `allEvents` (raw `readStages()` output) rather than the pre-collapsed `latestPerStage()` map, so gap 4 has data to render from. `latestPerStage()` stays in `board.js`/`activity.js` for cheap summarization elsewhere, but `StageStrip` itself takes the raw array and derives both "latest per stage" and "full history per stage" internally.
- `dashboard/src/components/StageStrip.jsx` — same visual design (icon/color per status, skipped now rendered dim), tooltip extended to include machine and cost (`· {machine} · ${cost_usd.toFixed(2)}` when present), and `onStageClick(seg)` now opens a small inline popover/list of that stage's `events` with timestamps (reuse `Markdown.jsx`-adjacent simple list markup, no new dependency) instead of delegating straight to the card's `onSelect`. Falls back to `onSelect(pr)` only when the clicked stage really has one event (nothing extra to show), satisfying "click a stage to see its events, with times" without inventing a second navigation path for the common case.

**Modified files, minimal footprint at the two hot spots:**

- `dashboard/electron/main/mr_review.js`: add exactly one new trailing option to the *current* (not the stale #368) signature — `listPipelinePrs(listOpenPrs, { ..., autoMergeShadow = null, stagesDir = null, liveDispatch = null } = {})` — and inside the per-PR map, read `readStages(ticketRef, stagesDir, prRepo)` (full array, not latest-only) plus `isLiveNow` via the existing `taskIsTicket` pattern from `activity.js`, attach as `stages` (raw events) on the returned object. Import `readStages` from `../../webhook-server/ticket_stages.js` and `taskIsTicket` — check whether `activity.js` exports it already (it does since #368 added `export { TERMINAL_STAGE_ORDER, taskIsTicket }`, confirmed present on current `main`); reuse that export, don't redefine.
- `dashboard/electron/main/index.js`: add `stagesDir: STAGES_DIR, liveDispatch: readDispatchStatus()` to the *current* `mr:list` handler's options literal (which now also has `autoMergeShadow`). One line, after the existing one.
- `dashboard/electron/main/board.js` / `activity.js`: already carry `stages: latestPerStage(events)` (no drift since #368, safe to reuse as-is) — add the raw `events` array alongside the latest-per-stage map so `StageStrip` can do its own full/latest split; `ProjectBoard.jsx`/`MrReview.jsx` pass `events` through to `StageStrip` instead of (or alongside) the collapsed map.
- `dashboard/src/components/MrReview.jsx`, `ProjectBoard.jsx`: render `<StageStrip events={...} rebase={pr.rebase} isLiveNow={pr.isLiveNow} now={Date.now()} onStageClick={...} />` — two-line adds, away from ticket #341's unrelated `amReport` banner block (different line range, confirmed no overlap by diffing current `main`).
- `dashboard/webhook-server/ticket_stages.js`: no change needed — `mutation` is already in `VALID_STAGES`; the gap is only in the dashboard-side label map.

## Acceptance criteria mapping

| AC | Covered by |
|---|---|
| Stage strip on PR and ticket cards, derived not stored | `StageStrip`/`deriveSegments` read `readStages()`/`events` live each render; nothing new is persisted |
| Failed stage shows message + remediation | `deriveSegments`'s code/detail parsing + trimmed `REMEDIATION_BY_CODE` |
| #215 refusals show as failed order/request stage | `OUT_OF_ORDER → 'Order check'` relabel of the `merging` segment (the only key the real stage log ever uses for a request-stage refusal — confirmed via `refusal_log.js:38`) |
| Works for every onboarded project | `stageKey`/`readStages` are already project-keyed (#216); `mutation` added to the dashboard's stage vocabulary so no pipeline stage used by any onboarded project is silently dropped |
| Real screenshots in the PR (#126) | Use the existing `dashboard/scripts/capture_screenshot.mjs` (no new infra — #126 is about iOS Simulator capture for clarity-captions, unrelated to this Electron/React change): build the dashboard, seed a fixture stage-log file under `~/.claude/logs/ticket-stages/` covering passed/failed/running/stalled, make sure MR Review or the board is the view that loads, and attach the real screenshot — not the "N/A — no UI" the last attempt wrote despite visibly adding a UI element |
| Component tests with fixture stage logs | See test list below |

## Tests to write FIRST

The issue has no "How we'll try to break it" or "Attacks" section (the triage bot flagged this ticket as missing a "What to build" section; its "Solution" serves that role but confirms there's no attack list to carry forward). Tests below are derived from the acceptance criteria, Gil's comment, the real collaborator's actual behavior (read above, not assumed), and the generic misuse categories:

**`stage_strip.test.js` (`deriveSegments`, against the real detail-string shapes written by `ticket_stages.js`/`refusal_log.js`/`merge.js`, not invented ones):**
1. All-passed ticket → every stage up to `done` shown passed, nothing after `done`.
2. Partial ticket (only `claimed`/`planning` have events) → `executing` onward render `pending`/grey, not omitted (closes gap 1 — the case no existing #368 test covers).
3. Failed at `gate` with plain `CODE: message` detail (the shape `merge.js`'s `stage('gate','failed',...)` actually writes) → failed, message, remediation; stages after `gate` are `pending`, not silently missing.
4. Refused `OUT_OF_ORDER` with the real `refused CODE: message` shape from `refusal_log.js` → relabeled "Order check", message, remediation explicitly null (no fabricated generic text for a message-only refusal).
5. A ticket log that reaches `mutation` with status `started` → segment present with label, not dropped (closes gap 3).
6. `started` + `isLiveNow: true` + recent timestamp → `started` (animated); `started` + `isLiveNow: false` → `stalled` regardless of elapsed time (the #161 regression test, direct negative: a stale/fake "running" claim must never appear live).
7. `started`, `isLiveNow: true`, but last event older than `stallMinutes` → `stalled` (silently-stuck process, live dispatch slot held but nothing moving).
8. Two attempts at the same stage (`executing` failed once, retried, now `passed`) → latest status wins for the segment's headline state, but the segment's `events` list retains both attempts in order (closes gap 4 — no existing test distinguishes "latest" from "history").
9. Malformed/empty input: `deriveSegments({})`, `deriveSegments(null)`, a stage object with a garbage `timestamp` (`"not-a-date"`), an event with `stage` missing or not in `VALID_STAGES_ORDERED` (forward-compat for a stage name added later than this code) → never throws, unknown/garbage entries are ignored rather than rendered as nonsense.
10. `rebase.status === 'conflict'` with no `files` array → still renders a failed "Rebase" segment with a generic message, doesn't throw on the missing array.
11. Huge input: a stage log with hundreds of repeated `started`/`failed` events for one stage (a pipeline stuck in a retry storm) → `deriveSegments` still returns in bounded time and the segment's `events` list doesn't blow up the render (cap or confirm no pathological behavior).

**Integration test against the real collaborator (`ticket_stages.js`), not a mock of it** — write real events via `recordStage()` into a temp `dir`, then `readStages()` → feed straight into `deriveSegments()`, asserting the pipeline end-to-end matches a hand-built fixture's result. This is the one #368 never had: every existing test hand-constructs the `stages` object, which would hide a real divergence between what `recordStage()` actually writes and what `deriveSegments` expects to parse.

**`stage_strip_component.test.jsx` (`StageStrip`, via `renderToStaticMarkup` matching house convention):**
12. Passed/failed/started/stalled/pending all render their distinct icon+color, including the newly-visible pending/grey segment.
13. Tooltip (`title` attribute) string contains the machine name and a formatted cost when present, and degrades gracefully (no "undefined"/"NaN") when `machine`/`cost_usd` are null — closes gap 2, the hover requirement that's currently silently unmet.
14. Clicking a stage with multiple events renders/exposes that stage's event list with timestamps (not just a pass-through to `onSelect`); clicking a stage with exactly one event still works without a crash (the `onSelect` fallback path).
15. Keyboard activation (`Enter` on a focused segment) fires the same handler as a click — existing accessibility behavior from #368, must not regress.
16. Empty `stages`/`events` input renders without throwing (empty-ticket case, e.g. a brand-new `claimed`-only card).

**Wiring tests (`mr_review.js`, `board.js`/`activity.js` already-existing test files — extend, don't duplicate):**
17. `listPipelinePrs` with a PR whose ticket has no stage file at all (not yet claimed, or the stage dir is wrong/unreadable) → `stages`/`isLiveNow` degrade to empty/false, the PR itself still lists (stage-log read failure must never hide a PR — same fail-soft contract as `rebaseStatus`/`sentBackTickets`/`closedTickets`/`autoMergeShadow` already follow in that function).
18. `liveDispatch` throwing or returning `undefined` (dispatch-status read failure, a real dependency-failure case) → `isLiveNow` resolves false, doesn't throw up through `listPipelinePrs`.
19. Two different projects both have an open ticket numbered the same (e.g. `#158` in marvin and in clarity-captions) → each PR's stage strip shows that project's own stage log, not the other's (regression guard for #216, the bug this ticket's data layer depends on).
20. Concurrent/out-of-order writes: a stage log file is being appended to (`recordStage`) by the pipeline at the same moment the dashboard's `mr:list` handler calls `readStages` — read either the pre- or post-append state cleanly, never a half-written/corrupt JSON parse throwing out of the IPC handler (wrap in the same try/catch fail-soft pattern already used for `rebased`/`shadow`/`closedKeys` reads in that function).