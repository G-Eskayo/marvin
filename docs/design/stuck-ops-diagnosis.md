# Stuck Ops Diagnosis: Bare Push Without Change Detection

## Issue Summary

When a bare push updates a PR's head commit without any associated GitHub issue/label/comment change, the dashboard cannot detect that update. The generic change detector (`createChangeDetector`) only sees issue updates, not raw commit changes. This leaves the PR's Approve button with a stale merge operation (error/reengaged/interrupted state), even after the underlying problem has been fixed.

## Detection Gap Analysis

### Current Flow (Broken)

1. **Generic Change Detector** (`createChangeDetector`): Polls the repo's newest issue with ETags every ~20s. Detects changes to issue/PR metadata (comments, labels, state), but **misses bare commits** since they don't update the issue's `updated_at`.

2. **Stuck Op Detection**: The dashboard tracks merge ops in error/reengaged/interrupted state. When such a state is reached, the op carries the commit sha (`head`) that failed.

3. **Recovery Mechanism**: When the head commit changes (via a new push), the op should be reset to idle, allowing a fresh Approve attempt. However:
   - No current code path detects when `pr.headRefOid` changes after a bare push
   - Without that detection, `opForHead` continues to read the old op
   - The renderer never sees a refresh trigger for the card

### Why the Gap Exists

The generic change detector's issue endpoint (`GET /repos/{repo}/issues?state=all&sort=updated`) returns the newest issue by `updated_at`. A bare push (no comment, label, or issue edit) does not bump `updated_at` on the PR itself. The detector correctly avoids false positives from GitHub's frequent ETag changes (marvin#603), but this makes it blind to commit-only updates.

## Diagnosis: Three Defects in Recovery Code

The head-watch mechanism (`createHeadWatcher` + `startHeadWatch` + evidence script) was added to detect when a PR's head changes, but three defects prevent it from working:

### Defect 1: Backwards Logic in `createHeadWatcher` (gh_watch.js:260)

**Original Code (Broken)**:
```javascript
const reachedWatchedHead = w.head && sha === w.head && known.sha !== w.head
if (known.sha !== undefined && (sha !== known.sha || reachedWatchedHead)) changed.add(w)
```

**Problem**: 
- The condition `sha === w.head` fires when we've reached the OLD head (the one that failed). We should fire when we've moved AWAY from it.
- The `known.sha !== undefined` gate prevents the first probe from ever firing, even if the head has already changed while the app was closed.

**Fix**:
```javascript
const leftWatchedHead = w.head && sha !== w.head
if ((known.sha !== undefined && sha !== known.sha) || leftWatchedHead) changed.add(w)
```

Now fires when: the sha changed from a previously-known value, OR we're watching for a specific head and it differs (enabling detection of changes that happened before the first watch tick).

### Defect 2: Evidence Script Spawns New Instance (stuck_ops_evidence.mjs:23)

**Original Code (Broken)**:
```javascript
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], {
  env: captureLaunchEnv(process.env),
  stdio: 'ignore'
})
// ... connects to new instance's CDP port
// new instance's mergeOps is empty, reports zero stuck ops
```

**Problem**: The script spawns a fresh Electron instance to query, but that new instance has empty `mergeOps` in memory (it just started). It should query the RUNNING dashboard instead.

**Fix**: Connect to the existing running dashboard via its CDP port (tries common ports 9222–9225 first).

### Defect 3: Silent Error Handling (stuck_ops_evidence.mjs:49)

**Original Code (Broken)**:
```javascript
window.electronAPI
  .invoke('mr:stuckOps', [])
  .then((ops) => resolve(ops || []))
  .catch(() => resolve([])) // Silent failure — returns empty array
```

**Problem**: Any error (preload not set up, IPC timeout, dashboard not running) silently returns `[]`, making it impossible to distinguish "no stuck ops" from "could not measure."

**Fix**: Throw errors instead of silently returning empty:
```javascript
.catch((err) => reject(err))
```

Now the caller can see when measurement failed vs. succeeded with zero stuck ops.

## Acceptance Test Plan

1. **Unit Tests** (passing): New tests in `gh_watch.test.js` verify:
   - Head watcher fires when moving away from watched head
   - Head watcher correctly detects changes even on first probe when watching for a specific head

2. **Integration Check** (2026-11-26): The `stuck_ops_evidence.mjs` script should:
   - Connect to the running dashboard (not spawn a new one)
   - Report actual stuck ops count (zero if none, non-zero if some exist)
   - Throw if the dashboard is unreachable or IPC fails

3. **Recurrence Measurement**: The evidence script output will be sampled on the 2026-11-26 check date to measure how often bare pushes leave cards hung.

## Related ADRs / Tickets

- **marvin#555**: Check watch for PR status changes
- **marvin#603**: GitHub ETag stability fixes for change detector
- **marvin#940**: Multi-machine merge failover
