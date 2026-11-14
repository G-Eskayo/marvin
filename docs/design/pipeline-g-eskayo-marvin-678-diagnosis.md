# Diagnosis: Stuck MR Cards on Bare HEAD Pushes

## Problem
When a bare push (no comment/label/state change) updates a PR's HEAD, the MR Review card stays stuck showing the old failure state until the user manually refreshes.

## Root Cause Analysis

### 1. Change Detection Gap
- **createChangeDetector** (gh_watch.js) monitors the newest issue per repo
- A bare HEAD push changes neither the issue's `number` nor `updated_at`
- Therefore, `createChangeDetector` sees no change and does not trigger refresh
- Result: githubState never hears about the new head SHA

### 2. Card Recovery Blocked
- The card calls `opForHead(op, pr.headRefOid)` on mount
- `opForHead` checks: if the op's head differs from the current PR head, return idle state
- **But**: `pr.headRefOid` is stale—it was read before the push and never refreshed
- Without a refresh signal, the old head SHA stays in memory
- Result: `opForHead` cannot detect the mismatch

### 3. Why This Matters
- A failure (e.g., rebase conflict) gets marked on commit ABC
- User pushes DEF to fix the conflict
- Card shows "Rebase conflict" anyway
- User has no way to signal the card to try again except a full page reload

## Solution: Head Watcher

### Implementation
1. **createHeadWatcher** (gh_watch.js): New watcher type, similar to createCheckWatcher
   - Polls `GET /repos/{repo}/pulls/{number}` with ETag on each ~20s tick
   - Detects when `head.sha` changes
   - Fires onChange only when the SHA actually differs

2. **stuckOps()** (merge_ops.js): Expose ops in error/reengaged/interrupted state
   - Called by the head watcher to know which PRs to watch
   - Returns {url, repo, number, head} for each stuck op

3. **startPrHeadWatch()** (index.js): Wire the watcher into the app lifecycle
   - Watches stuckOps() candidates on a 20s rhythm
   - On head change, resets the stuck op to idle
   - Refreshes the MR list and sends 'mr:mergeEvent' to re-render

### Behavior
- Merge starts → fails due to rebase conflict
- Card shows error and waits for new attempt
- User pushes fix to the PR
- Head watcher sees the new SHA on its next tick (~20s)
- Op is reset to idle, card shows "Ready to merge" again
- User can Approve without page reload

## Code Review Fixes (Second Implementation)

### Defect 1: Overly Broad Op Reset
- **Location**: dashboard/electron/main/index.js:330-340
- **Issue**: `onChange` callback received only `repo`, so a push to PR #1 reset every stuck op in that repo
- **Fix**: Changed watcher to report the specific PR `{repo, number, head}`, and only that op is reset
- **Impact**: Prevents a push to one PR from silently clearing errors on sibling PRs in the same repo

### Defect 2: Head Comparison Never Happens
- **Location**: dashboard/webhook-server/gh_watch.js:254-265
- **Issue**: Watcher stored `w.head` (what to watch for) but never compared against it
- **Fix**: On first 200 response, compare new SHA against `w.head`; only fire if it matches or SHA changed
- **Impact**: After app restart, a pushed PR whose new SHA landed before the watcher's first probe no longer stays stuck

### Defect 3: Evidence Script Had Typo
- **Location**: dashboard/scripts/stuck_ops_evidence.mjs:29
- **Issue**: Used `fs.dirname` instead of `path.dirname` (fs module has no dirname)
- **Fix**: Import path module and use `path.dirname`

### Defect 4: Evidence Script Reads Empty State
- **Location**: dashboard/scripts/stuck_ops_evidence.mjs:15
- **Issue**: Created new empty `createMergeOps()` instead of reading running app's state
- **Fix**: Spawn the app and query it via IPC for actual stuck ops; added mr:stuckOps IPC handler
- **Impact**: 2026-11-26 check now reads real production data, not fabricated zeroes

## Evidence & Metrics
- **2026-11-26 check**: How often do bare pushes leave cards stuck?
- Probe: stuck_ops_evidence.mjs spawns the app and queries mr:stuckOps via IPC
- Signals success: count stays near zero in production
- Confirms: head watcher reliably detects and resets stuck ops on new pushes
