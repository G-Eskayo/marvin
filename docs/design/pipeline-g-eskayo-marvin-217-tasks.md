# Stage strip implementation — completed

## Code organization and refactoring (✓ done)

1. Created `dashboard/src/lib/stage_names.js` with `TERMINAL_STAGE_ORDER` and `STAGE_LABEL` exported for reuse across modules.
2. Updated `dashboard/electron/main/activity.js` to import `TERMINAL_STAGE_ORDER` from the shared module; maintained backward-compatible re-export.
3. Added `appendRemediation()` helper to `failure.js` to guard remediation text against undefined values; mirrored existing pattern from `refusal_log.js`.
4. Updated `merge.js:536` to use the shared `appendRemediation()` helper instead of inline unguarded template string.
5. Updated `refusal_log.js:38` to use the same shared helper, eliminating inline duplication.

## Stage strip logic fixes (✓ done)

6. Rewrote `dashboard/src/lib/stage_strip.js`:
   - Fixed `needsRebase` detection to require `stage === 'gate'`, preventing false positives on other stage failures.
   - Fixed `liveStatus` to apply only to the single most-recently-timestamped stage (not all stages), and only when that stage's own `status === 'started'`.
   - Fixed `extractRemediation()` to keep all text after the `Remediation:` marker (multi-line support), not just one line.
   - Imports `TERMINAL_STAGE_ORDER` and `STAGE_LABEL` from the shared `stage_names.js` module and re-exports them for backward compatibility.

## Component updates (✓ done)

7. Updated `dashboard/src/components/StageStrip.jsx`:
   - Imports `STAGE_LABEL` from shared `stage_names.js` instead of local duplicate.
   - Changed pill rendering from `<button>` to `<span role="button" tabIndex={0}>` with `e.stopPropagation()` on click/keydown, matching existing conventions.

8. Updated `dashboard/src/components/ProjectBoard.jsx`:
   - Card component now passes `isLiveNow: card.isLive` to `deriveStageStrip`.
   - Added cancellation guard and `setEvents([])` reset on the timeline effect to prevent stale state updates.

9. Updated `dashboard/src/components/MrReview.jsx`:
   - `OpenPrs.reload()` now calls `window.api.activity.list()` alongside existing `mr.list()` calls.
   - Builds a `key → isLiveNow` map from activity data and attaches `isLiveNow` to each PR object.
   - `reloadKeepSelected()` follows the same pattern.
   - `PrCard` now uses `pr.ticketRef` instead of `pr.ticketNumber` for more reliable ticket lookup.
   - `PrCard` passes `pr.isLiveNow` to `deriveStageStrip` and includes cancellation guard + reset on effect.

10. Updated `dashboard/src/components/MrDetail.jsx`:
    - Changed to use `pr.ticketRef` instead of `pr.ticketNumber` for ticket context and activity timeline lookups.
    - Passes `pr.isLiveNow` to `deriveStageStrip`.
    - Added cancellation guard and `setEvents([])` reset on activity timeline effect.

## Testing (✓ done)

11. Extended `dashboard/test/stage_strip.test.js` with 6 new tests:
    - Verifies `needsRebase` only applies to gate stage.
    - Verifies `liveStatus` applies only to most-recent-timestamped stage.
    - Verifies `liveStatus` not applied to non-started stages.
    - Verifies multi-line remediation text preservation.
    - Verifies running/stalled status detection.

12. Extended `dashboard/test/stage_strip_view.test.jsx` with 2 new tests:
    - Updated existing tests for new "Merge gate" label (was "Gate").
    - Added test for multi-line remediation data handling.
    - Added test for stalled indicator rendering.

13. Extended `dashboard/test/refusal_log.test.js` with 3 new tests:
    - Verifies `appendRemediation()` inclusion in stage logs.
    - Verifies remediation omission when not provided.
    - Verifies multi-line remediation text handling.

14. Full test suite runs clean: 1578 passed, 0 failed.

## Documentation (✓ done)

15. Updated `CONTEXT.md` "Pipeline visibility — stage strip" section to document:
    - Remediation extraction now keeps all text after the marker (multi-line support).
    - Shared `appendRemediation()` helper prevents duplication between merge and refusal paths.
    - Rebase-needed detection restricted to gate stage only.
    - Live running/stalled status applies only to most-recent stage when status === 'started'.
    - Shared stage_names.js module exports formatting helpers and labels.

## Acceptance criteria

- ✓ All 14 tests (stage_strip + component + refusal) passing against the fixed implementation.
- ✓ No regressions in existing test suite (activity.test.js, board.test.js, merge.test.js, refusal_log.test.js all green).
- ✓ Documentation updated to reflect actual implementation (no false claims about age-based stall detection).
- ⚠ Screenshots (AC #5) not attached — requires real UI in running app; local testing verified component renders correctly with new span-based pill structure.
