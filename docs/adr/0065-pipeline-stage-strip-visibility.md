# ADR 0065: Pipeline Stage Strip Visibility

Date: 2026-10-09  
Status: Accepted  
Related: G-Eskayo/marvin#217, [Pipeline Visibility Plan](../../docs/plans/pipeline-visibility-2026-10-07.md)

## Problem

Debugging ticket and PR state requires SSH + log archaeology into `.claude/logs/ticket-stages/`. The dashboard shows the final pipeline history in a drill-down, but only as a vertical list, with no way to see the high-level "where is it now?" at a glance or to spot patterns like "most PRs stall here." 

Retry storms (70% of output tokens) and stalled approvals can't be diagnosed without that context visible in the place where the ticket/PR sits.

## Decision

Render a **horizontal stage strip** above the vertical pipeline history on both ticket cards (board view and drill-down) and PR cards. The strip shows one pill per canonical stage in pipeline-execution order (`claimed → planning → executing → verifying → gate → merging → versioning → rebuilding → done`), with a symbol and color for each stage's **latest** status:

- ◌ **pending** (no event yet) — neutral gray  
- ✓ **passed** — emerald  
- ✕ **failed** — red  
- ◐ **running** — blue  
- ⏱ **stalled** (no event for N minutes) — amber  
- ⟳ **needs rebase** (gate failure with REBASE_CONFLICT code) — amber  
- ∅ **skipped** — dim neutral  

### Stall thresholds (per-stage)

A stage with a `status: "started"` event older than its threshold is stalled:
- Default: 10 minutes (`claimed`, `planning`, `executing`, `verifying`, `merging`, `versioning`, `rebuilding`, `done`)
- `gate`: 35 minutes (just under the `GATE_TIMEOUT_MS` 40-minute abandon cutoff)

Stall detection **never** uses `isLiveNow === false` as proof (could be running elsewhere); only `isLiveNow === true` positively overrides a stale timestamp.

### Remediation lookup

Failed stages show their refusal code + human-readable remediation text on hover. The code is extracted tolerantly from detail strings in the shape `"CODE: message"` — missing codes degrade to raw detail text, never throw.

### Draft → ready visibility (Gil, 2026-10-09)

When `readyIfDraft` marks a draft PR ready on GitHub, a new `merging: passed` event is recorded:
```
"marked ready for review (owner pressed Approve on this draft)"
```

This gives the stage strip and history a discrete milestone to show.

### Cross-project correctness

Every piece of state threaded through (`repo` param on `window.api.activity.timeline`, `recordStage`, the draft→ready stage write) must never default to marvin implicitly, so the strip works identically for clarity-captions, portfolio, mobile, or any onboarded project (#217's explicit AC).

## Consequences

**Benefits:**
- High-level pipeline state visible at a glance on both ticket and PR cards  
- Stalled stages immediately spot-able (no more "is this stuck or running on the other machine?" guessing)  
- Debugging "where did this PR get stuck?" goes from 5-minute log archaeology to 1-second click  
- Retry storms tied to specific stages become visible in aggregate  
- "Needs rebase" becomes a distinct, labelable state with remediation  

**Trade-offs:**
- Card's stage strip adds ~1 extra IPC call per ticket with timeline data (already gated on `card.hasTimeline`); not the drill-down call (that still only fires on selection)  
- Depends on `ticket_stages.py`'s Python-side events being written with the same schema (already proven true by existing `PipelineHistory` rendering)  
- Horizontal layout trades vertical space for horizontal; tickets with many old stages may wrap depending on screen width (acceptable — wrap is graceful)  

## Implementation

1. **`dashboard/src/lib/stage_strip.js`** — pure derivation function `deriveStageStrip(events, opts)`: events → 9-segment array with status, remediation, elapsed time.  
2. **`dashboard/src/components/StageStrip.jsx`** — React presentational component: renders segments, shows remediation on hover, scrolls to matching entry in `PipelineHistory` on click.  
3. **`failure.js`** — export `REMEDIATION_BY_CODE` built from RULES + inline refusals.  
4. **`merge.js`** — consistency fix: prefix `versioning` failed-stage detail with `VERSION_BUMP_FAILED:` code; add stage recording for draft→ready.  
5. **`ProjectBoard.jsx`** — import shared helpers (`STAGE_LABEL`, `money`, `when`), render `StageStrip` in `Card` and above `PipelineHistory` in `TicketDrilldown`.  
6. **`MrReview.jsx` + `MrDetail.jsx`** — fetch ticket timeline via `window.api.activity.timeline(pr.ticketNumber, pr.repo)`, pass to `deriveStageStrip` with PR's live fields (`checks`, `conflicts`, etc.) as overlay, render strip.  

## Verification

- **Unit tests** (`stage_strip.test.js`): empty/malformed data, huge history, every status, stall thresholds, code extraction, remediation lookup, cross-stage persistence, isLiveNow override semantics.  
- **Component tests** (`StageStrip.test.jsx`): passed/failed/running/needs-rebase rendering per AC; hover remediation; scroll-to-history on click.  
- **Cross-project test**: two repos with ticket #158 each produce independent strips; project without CI shows no `gate` segment; project profile skipping `mutation` stage shows it skipped, not failed.  
- **Screenshots** per repo's hard UI rule: passed, failed-at-gate, refused-at-order, needs-rebase, running states on both ticket and PR cards.
