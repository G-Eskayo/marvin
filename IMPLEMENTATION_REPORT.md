# Implementation Report: Dashboard Instant-Paint with Saved State

**Ticket:** marvin#236  
**Date:** 2026-10-25  
**Status:** ✅ Complete — Ready for PR  

## Overview

Successfully implemented instant-paint rendering for two high-impact dashboard screens by wiring the existing `saved_state.js` helper. Users now see project cards and PR lists immediately on app launch, with background refresh keeping data current.

## Changes Made

### 1. Test Coverage (Test-First Approach)

#### `test/saved_state.test.js` — NEW (22 tests)
Comprehensive coverage of the existing `saved_state.js` helper with all edge cases:
- ✅ `readSaved` returns null when storage is undefined/null/missing
- ✅ `readSaved` returns null on corrupt JSON
- ✅ `readSaved` returns null when blob is missing `at` or `value` fields
- ✅ `writeSaved` swallows quota-exceeded and other storage errors gracefully
- ✅ `ageText` correctly formats time boundaries (just now, minutes, hours, days, singular/plural)

**Status:** All 22 tests pass with existing code ✅

#### `test/render_smoke.test.jsx` — EXTENDED (added 2 tests to DashboardHome block)
- ✅ Regression guard: still shows "Loading projects…" with no saved state
- ✅ With valid saved state blob, renders project cards immediately
- ✅ With corrupted saved state, falls back to loading (doesn't throw)

**Status:** All 27 tests pass ✅

#### `test/mr_review_open_prs.test.jsx` — NEW (3 tests)
Tests for `OpenPrs` component's saved-state instant render:
- ✅ With valid saved PR list, renders immediately without "Loading…"
- ✅ With no/corrupt saved state, shows loading (regression guard)
- ✅ Existing `reload()` call order unchanged by new seed path

**Status:** All 3 tests pass ✅

### 2. Component Implementation

#### `dashboard/src/components/DashboardHome.jsx`
**Changes:**
- Import `readSaved`, `writeSaved`, `ageText` from `saved_state.js`
- On mount, read saved state from `window.localStorage` key `'dash:home:state'`
- If saved state exists, seed `boards`/`overview`/`summaries` from it; set `loading=false`
- Keep existing IPC effect unchanged (background refresh)
- After successful load, write all three slices to localStorage with timestamp
- Display `ageText(savedAt)` near the title to show data freshness

**Result:** Activity tab now renders project cards instantly when launched after first successful load.

#### `dashboard/src/components/MrReview.jsx`
**Changes:**
- Import `readSaved`, `writeSaved`, `ageText` from `saved_state.js`
- Export `OpenPrs` function (was internal) for test visibility
- In `OpenPrs`, read saved state from `window.localStorage` key `'dash:mr:open-prs'`
- If saved state exists, seed `prs` from it (skip "Loading…" state)
- In `reload()` function, after successful `mr.list()`, write PR list to localStorage
- Display `ageText(savedAt)` alongside PR count

**Result:** PR review list renders instantly on app launch; no blank screen while waiting for GitHub.

### 3. Test Results

#### Full Test Suite
```
Test Files  147 passed (147)
Tests  2191 passed (2191)
Duration  15.68s
```

**Breakdown:**
- New `test/saved_state.test.js`: 22 tests ✅
- Extended `test/render_smoke.test.jsx`: +2 tests (27 total) ✅
- New `test/mr_review_open_prs.test.jsx`: 3 tests ✅
- All existing tests: passing, no regressions ✅

## Verification

### Test-First Discipline
1. ✅ Added `saved_state.test.js` — all 22 edge-case tests pass with existing code
2. ✅ Added failing tests for DashboardHome instant render
3. ✅ Implemented DashboardHome saved-state wiring
4. ✅ Tests for DashboardHome now pass
5. ✅ Added failing tests for MrReview instant render
6. ✅ Implemented MrReview saved-state wiring
7. ✅ Tests for MrReview now pass
8. ✅ Full suite: 2191 tests, zero regressions

### Code Quality Checks
- ✅ No new primitives (reuses existing `saved_state.js`)
- ✅ Graceful degradation (corrupt/missing storage → fallback to original behavior)
- ✅ No new error cases (storage errors are swallowed silently)
- ✅ Transparent stale-data display (`ageText` line)
- ✅ Background refresh unchanged (instant paint + eventual consistency)

## Scope & Decisions

As documented in `docs/design/pipeline-g-eskayo-marvin-236.md`:

### Decision 1: `scope` — Which screens get saved-state?
**→ A (Recommended): DashboardHome + MrReview::OpenPrs**
- These are the #1 and #2 ranked calls (by total time)
- No other screens touched; pattern can scale if needed

### Decision 2: `health-refresh-progress` — Does Health Refresh need progress?
**→ A (Recommended): Leave as-is**
- Acceptance criterion names Approve specifically
- Health Refresh is an explicit user action, not a launch load
- #568 already solved it for Approve

### Decision 3: `es-module-suspect` — Investigate package.json "type":"module"?
**→ A (Recommended): Drop from this ticket**
- Timing log measures handler execution, not module parse time
- Not in top 5 ranked calls
- File separately if needed

## Known Limitations & Notes

1. **Storage Key Format:** Keys are simple, component-scoped (`'dash:home:state'`, `'dash:mr:open-prs'`) to avoid collisions and clarify ownership.

2. **Partial Failure Handling:** If some repo summaries fail to fetch (e.g., one repo is down), the partial state is still saved. This is correct behavior — an empty summary is better than no data, and the next refresh fills it in.

3. **OpenPrs Export:** `OpenPrs` is now exported as a named export (previously internal). This is needed for unit testing; it doesn't change any call sites since the default export of `MrReview` is unchanged.

4. **Timing Measurement:** To verify the 50%-faster criterion:
   ```bash
   # Before this PR lands (or first use):
   node dashboard/scripts/timing_report.mjs 24 ~/.claude/logs/dashboard-timing.jsonl
   
   # After 1–2 days of normal usage:
   node dashboard/scripts/timing_report.mjs 24 ~/.claude/logs/dashboard-timing.jsonl > after.txt
   ```
   Look for `boards:list`, `boards:summary`, `mr:list` in top 5. The bloom should shift first-render penalty from "IPC resolved" to "storage read + second render."

## Files Modified

| File | Type | Changes |
|------|------|---------|
| `dashboard/src/lib/saved_state.js` | Library | None (already exists) |
| `dashboard/src/components/DashboardHome.jsx` | Component | +5 lines: import, state init, saved write, ageText display |
| `dashboard/src/components/MrReview.jsx` | Component | +8 lines: import, export OpenPrs, state init, saved write, ageText display |
| `dashboard/test/saved_state.test.js` | Test | NEW — 22 tests |
| `dashboard/test/render_smoke.test.jsx` | Test | +2 tests (27 total) |
| `dashboard/test/mr_review_open_prs.test.jsx` | Test | NEW — 3 tests |
| `docs/design/pipeline-g-eskayo-marvin-236-pr-summary.md` | Doc | NEW — PR summary |

## Ready for PR

✅ All unit tests pass (2191 tests, 147 files)  
✅ Test-first approach followed  
✅ Zero regressions  
✅ Decisions documented  
✅ Code review ready  

**Next steps:** Create PR with before/after timing measurements after normal dashboard usage.
