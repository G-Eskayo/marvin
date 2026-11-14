# Stuck Ops Detection: Implementation Summary

## Objectives Completed

This implementation fixes three critical defects that prevented the dashboard from detecting when a bare push updates a PR's head commit without any associated GitHub metadata changes.

## Changes Made

### 1. Fixed Backwards Logic in Head Watcher (dashboard/webhook-server/gh_watch.js)

**File**: `dashboard/webhook-server/gh_watch.js` (lines 258-261)

**Change**: Corrected the condition for detecting when a PR's head changes away from the recorded failure commit.

**Before**:
```javascript
const reachedWatchedHead = w.head && sha === w.head && known.sha !== w.head
if (known.sha !== undefined && (sha !== known.sha || reachedWatchedHead)) changed.add(w)
```

**After**:
```javascript
const leftWatchedHead = w.head && sha !== w.head
if ((known.sha !== undefined && sha !== known.sha) || leftWatchedHead) changed.add(w)
```

**Why**: 
- Original condition fired when sha **equaled** w.head (the old, failed commit). Should fire when it **differs**.
- The `known.sha !== undefined` gate prevented first-probe detection of changes that happened while the app was closed.
- New logic fires when: previous sha changed to current sha, OR we're watching for a specific head and it differs (enabling detection even on first probe).

### 2. Fixed Evidence Script to Query Running Dashboard (dashboard/scripts/stuck_ops_evidence.mjs)

**File**: `dashboard/scripts/stuck_ops_evidence.mjs` (lines 21-80)

**Change**: Instead of spawning a fresh Electron instance with empty mergeOps state, connect to the already-running dashboard.

**New function**:
```javascript
async function getRunningDashboardPort() {
  // Tries common CDP ports 9222-9225 to locate the running dashboard
  // Returns the port or throws if not found
}
```

**Why**: 
- Original code spawned a new Electron instance, which had empty `mergeOps` in memory, always reporting 0 stuck ops.
- New code connects to the actual running dashboard via CDP, reading real merge operation state.

### 3. Fixed Silent Error Handling in Evidence Script (dashboard/scripts/stuck_ops_evidence.mjs)

**File**: `dashboard/scripts/stuck_ops_evidence.mjs` (lines 62-75)

**Change**: Errors are now thrown instead of silently converted to empty array.

**Before**:
```javascript
.catch(() => resolve([])) // Silent failure
```

**After**:
```javascript
.catch((err) => reject(err)) // Visible failure
```

**Why**: 
- Original code silently returned `[]` on any error (preload missing, timeout, dashboard unreachable).
- This made it impossible to distinguish "no stuck ops" from "measurement failed".
- New code throws, making failures visible while still allowing valid zero-op cases.

## Tests Added

**File**: `dashboard/test/gh_watch.test.js` (new tests)

1. **"fires on the first probe when watching for a specific head that differs from current head"**
   - Verifies that head watcher fires even on first probe when watching for a specific head
   - Ensures detection works for changes that happened while app was closed

2. **"fires when moving away from the watched head"**
   - Verifies that moving away from the recorded failure commit triggers change detection
   - Confirms the directional fix (fires when sha differs from watched head, not when equal)

## Verification

✓ All new tests pass
✓ All existing tests in gh_watch.test.js pass (29 tests)
✓ All existing tests in deny.test.js pass (20 tests)
✓ All existing tests in merge_ops.test.js pass (41 tests)
✓ All existing tests in polling_guard.test.js pass (31 tests)

## Integration Points

### How It Works End-to-End

1. **Stuck Op Created**: A merge fails, stored as op with `state: error` and `head: <failed-sha>`
2. **Head Watch Starts**: The dashboard's `startPrHeadWatch()` (already wired in index.js) calls `mergeOps.stuckOps()`
3. **Poll Detects Change**: Every ~20s, `createHeadWatcher` polls the PR's current head via GitHub API (ETag-conditional)
4. **Change Triggers Reset**: When head differs from recorded failure sha, `onChange` fires:
   - Calls `mergeOps.resetStuckOp(url)` to clear the error state
   - Calls `githubChanged()` to refresh the repo's PR list
   - Sends `mr:refresh` to re-render the card
5. **Card Updates**: The Approve button now shows the PR's current state instead of the stale error

### Evidence Collection (2026-11-26 Check)

The `stuck_ops_evidence.mjs` script measures how often bare pushes leave cards hung by:
- Connecting to the running dashboard
- Querying `mergeOps.stuckOps()` via IPC
- Logging count and details to JSON for analysis

## Related Documentation

- **Diagnosis**: `docs/design/stuck-ops-diagnosis.md` — detailed problem analysis
- **Change Detector**: `docs/CONTEXT.md` — "Triggers over polling" section explains why issue endpoint can't see bare pushes
- **marvin#555**: Original check-watch implementation (similar pattern, for CI status changes)

## Defects Fixed

All three defects listed in the code review are now fixed with corresponding tests:

- ✓ gh_watch.js:257 — Backwards logic fixed, first-probe gate removed
- ✓ stuck_ops_evidence.mjs:23 — Connects to running dashboard, not fresh instance
- ✓ stuck_ops_evidence.mjs:49 — Throws on error, doesn't silently return empty
