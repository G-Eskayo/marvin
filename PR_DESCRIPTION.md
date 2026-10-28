# Dashboard instant-paint with saved state — marvin#236

## Summary

Implemented instant-paint rendering for two high-impact dashboard screens (`DashboardHome` and `MrReview::OpenPrs`) by wiring the existing `saved_state.js` helper. Users now see project cards and PR lists immediately on app launch, with background refresh keeping data current. Also fixed three robustness issues uncovered during code review: malformed saved state validation (`overview: null`/`[]`), error messaging for cached empty boards, and instant tab badge for PR count.

## Changes

### Components
- **`dashboard/src/components/DashboardHome.jsx`**
  - Tightened `validSaved` check: rejects `overview: null` and `overview: []` (not just non-objects)
  - Moved error message to "No project boards yet" branch (was silently swallowed for `boards: []`)
  - On mount: read saved state from localStorage; if valid, seed `boards`/`overview`/`summaries` instantly
  - On successful refresh: write all three slices to localStorage for next launch
  - Display `ageText(savedAt)` to show data freshness

- **`dashboard/src/components/MrReview.jsx` (OpenPrs)**
  - Exported `OpenPrs` as named export for test visibility
  - On mount: read saved PR list; if valid, seed `prs` instantly
  - On successful `mr.list()`: write PR list to localStorage
  - **New:** mount-only effect calling `onCount?.(prs.length)` when seeded (instant tab badge)
  - Display `ageText(savedAt)` alongside PR count

### Tests
- **`dashboard/test/render_smoke.test.jsx`** — DashboardHome block
  - Fixed `beforeEach`/`afterEach` to properly capture/restore `global.window` (present vs. absent)
  - Added test: `overview: null` fails validation → falls back to loading
  - Added test: `overview: []` (array) fails validation → falls back to loading
  - Added test: empty boards with error shows error message (structure verification)

- **`dashboard/test/mr_review_open_prs.test.jsx`**
  - Fixed `beforeEach`/`afterEach` to properly capture/restore `global.window` state
  - Test suite now properly isolates global state

## Test Results

```
Test Files  147 passed (147)
Tests       2198 passed (2198)  [+3 new tests]
Duration    55.32s
```

No regressions. All existing tests continue to pass.

## Acceptance Criteria Status

| Criterion | Status | Notes |
|-----------|--------|-------|
| **1. Cold start 50% faster** | Pending measurement | Current timing baseline needed; see Decisions below |
| **2. Instant layout with saved state** | ✅ Verified | Unit tests confirm instant paint when localStorage has data |
| **3. Reuse existing, no new primitives** | ✅ Verified | All mechanisms from existing `saved_state.js` (also proven in `MetricsPage.jsx`) |
| **4. Approve merge progress** | ✅ Confirmed | Already shipped in #568; no changes needed here |
| **5. saved_state.js coverage** | ✅ Verified | Existing `test/saved_state.test.js` covers edge cases |

## Decisions

<!-- marvin:decisions -->
### criterion-1-metric: How should "the slowest user-facing call is 50% faster" be satisfied for a UI-blocking fix that doesn't touch backend call time?

- [ ] A: Accept that `timing_report.mjs`'s backend ms is unchanged by this PR and use the criterion's own escape clause — state plainly why a saved-state/instant-paint fix cannot move `ipcMain.handle` execution time, post the current ranked table as the honest baseline, and argue the user-facing wait is cut by the saved-state mechanism instead, which the existing log doesn't capture
- [ ] B: Add a small new client-side metric (ms from mount to first meaningful paint, logged per screen) so "faster" can be measured directly for this mechanism, and compare that before/after instead of the backend table
- [ ] C: Expand this PR's scope to also cut backend call time for one of the top entries (e.g. trim the `files` field on `mr:list`), so the existing table genuinely moves

### scope: Which cold-start screens get saved-state wiring in this round?

- [ ] A: Just the two already wired — Activity home (`DashboardHome.jsx`) and MR Review's PR list (`MrReview.jsx` `OpenPrs`)
- [ ] B: Also the Queue widgets (`NextUpQueue.jsx`, `ActivityHover.jsx`, `ParallelToggle.jsx`, all calling `queue:list`)
- [ ] C: Every remaining GitHub-backed view dashboard-wide in one pass

### health-refresh-progress: Does Health's "Refresh" button need stage-by-stage progress this round?

- [ ] A: Leave as-is — the acceptance criterion names Approve specifically, and Refresh is an explicit user action, not a launch load
- [ ] B: Extend the same stage-progress pattern used for Approve (#568) to `health:refresh`

### es-module-suspect: Pursue the dashboard/package.json "type":"module" suspect in this PR?

- [ ] A: Drop it from this ticket — the timing log only measures handler/route execution, not module-parse time, and it isn't among the top 5 ranked calls; file a separate low-priority ticket if it matters
- [ ] B: Investigate and fix it here too

## What's still open

- **Criterion 1 measurement:** Requires real usage data after landing. Run `node dashboard/scripts/timing_report.mjs 24 ~/.claude/logs/dashboard-timing.jsonl` after 1–2 days of normal app usage to capture the ranked table; look for `boards:list`, `boards:summary`, and `mr:list` in the top 5 to confirm the instant-paint mechanism is working.
- **Scope decision:** If B or C is chosen, queue widgets will need the same wiring pattern in a follow-up PR.

## Notes

- Robustness fixes (items 5–7 from the design doc) are all included: malformed `overview` validation, empty-but-cached boards error display, and instant tab badge.
- All fixes are in-place code review corrections — no new files, no new abstractions.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
