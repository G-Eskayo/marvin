Writing the doc file was blocked (plan-only mode, no file edits) — so here's the complete plan inline.

## North-star fit

**Reuses before adding anything:** `ticket_stages.js`'s `readStages`/`VALID_STAGES` (#216, already project-keyed), `activity.js`'s `taskIsTicket`/`listTicketActivity` (the actual #161 fix already lives here), `board.js`'s `eventsByNumber` (already the full per-ticket event list), `index.js`'s existing `activity:timeline` IPC channel and `triggerHub.watchFiles('activity', ...)` live-refresh (the strip updates for free, no new watcher), `refusal_log.js`'s `REFUSAL_CODES` (#215's real source), and `ProjectBoard.jsx`'s existing `PipelineHistory`/`STAGE_LABEL`. Net new code: one pure module, one small component, one extraction — everything else is wiring existing facts into existing views.

**Simplest sufficient approach:** a pure `deriveSegments(stages, opts)` function, one component used in two places. No per-segment click/keyboard handling — PR cards and ticket cards are *already* click-to-open-detail, so "click a stage to see its events" is satisfied by letting the click bubble to the existing handler, not by adding a competing one.

**Tokens:** small one-time cost (<200 lines); pays back by making "where is this stuck" a glance instead of an investigation — directly what #161 and the three stuck-PR-368-conflict comments cost.

**Phone-OS direction:** `deriveSegments` stays pure/dependency-injected (`now`, `isLiveNow` passed in, nothing read from globals) — required for the ticket's own "used in MARVIN Mobile's Dashboard later."

**More capable, not more passive:** pure visibility, no automation — passes north-star-3 cleanly.

**Correcting the ticket's stated fit:** the issue body's illustrative strip (`plan ✓ → build ✓ → ... → order ✗ ... → gate · → merge ·`) uses stage names that don't exist in the real schema and puts "order" before "gate," which can't happen — order/base/CI/sent-back refusals are always recorded at the `merging` stage (confirmed in `refusal_log.js:38`). Gil's own later comment gives the real order (`claimed → planning → executing → verifying → gate → merging`), matching the actual schema — that's authoritative here; the issue body's example is illustrative wording only.

## Files read before planning

`ticket_stages.js`, `refusal_log.js`, `failure.js`, `merge.js`/`ci_status.js`/`code_review_gate.js` (every `refusal()`/`recordStage()` call site), `activity.js`, `board.js`, `boards.js`, current `mr_review.js` (post-#341), current `index.js`, `pr_order.js`, `preload/index.js`, `MrReview.jsx`, `ProjectBoard.jsx`, `MrDetail.jsx` (confirmed: no stage rendering there today — a real gap), test files (`mr_review.test.js`, `board.test.js`, `boards.test.js`, `refusal_log.test.js`, `render_smoke.test.jsx`), `vitest.config.js`/`package.json`, plus PR #368's full diff (the prior attempt, checked against current main).

## Why PR #368 kept conflicting, and where its design was simply wrong

`#339` added `autoMergeShadow` to `listPipelinePrs`'s options object on the exact line #368 also extended — unresolvable by rebase. #215/#216 are now closed, nothing blocks starting. Beyond staleness, #368's design had real bugs I won't repeat: a `REMEDIATION_BY_CODE` table claimed to be "imported from the webhook" but was actually a hand-copied duplicate; its refusal-label map didn't match the real `REFUSAL_CODES` set; `deriveSegments` skipped any stage with no event at all, contradicting the ticket's own example (`gate ·` shown even though not yet reached); it redefined `STAGE_LABEL` instead of reusing `ProjectBoard.jsx`'s; every segment got its own `role="button" tabIndex`, nested inside `ProjectBoard`'s `<button>` card — invalid markup; it added a new standalone component-test file against house convention (one shared `render_smoke.test.jsx`); and its tooltip showed a fixed clock-time instead of an elapsed duration, despite Gil's ask being explicitly about duration ("hung for 5 hours").

## Design (12 concrete pieces)

1. `dashboard/src/lib/stage_labels.js` (new) — extract `STAGE_LABEL` from `ProjectBoard.jsx` verbatim, add `CORE_STAGES`/`OPTIONAL_STAGES`.
2. `dashboard/src/lib/stage_strip.js` (new, pure) — `deriveSegments(stages, { isLiveNow, now, stallMinutes })`, walks `CORE_STAGES` always (pending if no event), appends `OPTIONAL_STAGES` only if present, computes `elapsedLabel` via the already-exported `formatRelativeTime` from `DashboardHome.jsx`.
3. Refusal relabeling inside `stage_strip.js`, importing real `REFUSAL_CODES` (`refusal_log.js`) and `REMEDIATION_BY_CODE` (new export, below) — `OUT_OF_ORDER`/`WRONG_BASE` → label "Order", rest → "Request"; `OUT_OF_ORDER` gets no generic remediation (its message is already self-describing).
4. `failure.js`: export `RULES` (currently un-exported `const`) and add `export const REMEDIATION_BY_CODE = Object.fromEntries(RULES.filter(r => r.remediation).map(r => [r.code, r.remediation]))`.
5. `board.js`: add `latestPerStage(events)` helper, put `stages: latestPerStage(events)` on each card next to existing `hasTimeline`. No signature change; confirmed this region didn't conflict in #368 either.
6. `mr_review.js`: append `stagesDir = null, liveDispatch = null` to `listPipelinePrs`'s options (after `autoMergeShadow`, not mid-line). Export `taskIsTicket` from `activity.js`; reuse it for `isLiveNow`. Fail-soft `readStages` exactly like every other best-effort field in this function.
7. `index.js`: one line in the `mr:list` handler passing `stagesDir: STAGES_DIR, liveDispatch: readDispatchStatus()` — both already imported.
8. `StageStrip.jsx` (new) — renders `deriveSegments` output, no `onStageClick`/no per-segment interactivity, tooltip carries message/remediation/time/machine/cost.
9. `PipelineHistory.jsx` (new) — extraction of the existing function out of `ProjectBoard.jsx`, used there unchanged and newly in `MrDetail.jsx`.
10. `MrReview.jsx`'s `PrCard` / 11. `ProjectBoard.jsx`'s `Card` — one line each adding `<StageStrip .../>`.
12. `MrDetail.jsx` — the one genuinely new wire-up: fetch `window.api.activity.timeline(Number(pr.ticketRef), pr.repo)` (already supports arbitrary repo, no new IPC) and render `PipelineHistory`, satisfying "click a stage to see its events" for PR cards (ticket cards already get this via `TicketDrilldown`).

Multi-project support and screenshots are verification steps, not new code — `stages`/`readStages` are already repo-keyed throughout; one thing to actually check rather than assume: the `foreignBoards` path in `boards.js` passes no `eventsByNumber`, so `stages: {}` → `StageStrip` must render `null`, not a stray all-pending strip.

## Tests written FIRST (25 cases)

**From the ticket + Gil's comments, each named:** all-passed; failed-at-gate with message+remediation; refused-at-order (`OUT_OF_ORDER`, message verbatim from `pr_order.js`'s real string, no fabricated remediation); every code in the real `REFUSAL_CODES` set relabels without crashing; running (live+recent→started); **#161 regression** (not-actually-live+recent-"started" event→stalled, never inferred from a label); live-but-silent-past-threshold→stalled; boundary at exactly the stall threshold; click-propagation (strip must not swallow the card's own onSelect — direct regression test for the #368 markup bug); hover shows time+machine+cost; MrDetail renders real stage events with times via `activity.timeline`; end-to-end `listPipelinePrs` with a refusal written through the *real* `recordRefusal`/`recordStage` writers (not a hand-built fixture); same fixtures run for marvin and a non-marvin repo; skipped stages render as grey placeholders, not omitted.

**Misuse the ticket's section didn't name:** empty stages → null render, no throw; malformed event (missing/bad timestamp, non-string detail) → safe fallback, no throw; unknown future stage key → ignored; `readStages` throwing → PR still renders with `stages: {}`; huge event history → O(n), no quadratic blow-up (timed); concurrent write mid-poll → pure function means a stale read renders consistently, not torn; unfamiliar `machine` value → tooltip still renders; out-of-schema `status` value (hand-edited JSON) → treated as pending, doesn't crash the card; repeated `started` events with no terminal between → latest wins, asserted explicitly; stale `claimed:` label with zero stage events and not live → never shows an animated segment (the literal #161 scenario); refusal-message tests assert against the real collaborator's output, not a mock string, so they break if `pr_order.js`/`refusal_log.js` ever change format without this test changing.

**Where they land:** `dashboard/test/stage_strip.test.js` (new, pure-logic file — house convention), additions to the existing `render_smoke.test.jsx` (component smoke, no new file), additions to existing `mr_review.test.js` and `board.test.js`, and a `REFUSAL_CODES`-driven loop (imported, not hand-copied) covering the refusal-relabel cases. Run via `cd dashboard && npm test`.