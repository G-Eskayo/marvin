# Browser Lifecycle & Clone Directory Cleanup (#189)

## Summary

This implementation addresses two issues:
1. **Browser lifecycle management** in Playwright-based tests
2. **Orphaned code_sign_clone directory cleanup** from crashed browser processes

## Changes

### 1. Browser Test Fixes (snapshot, labels, code-layer)

**Problem**: Tests were using `channel: 'chrome'` which requires Google Chrome to be installed, and the `after` hook was not properly awaiting async cleanup.

**Fix**:
- Changed `chromium.launch({ channel: 'chrome' })` to `chromium.launch()` to use bundled Chromium
- Changed `after(() => browser?.close())` to `after(async () => { await browser?.close() })` to properly await async close

**Files modified**:
- `brain-map/tests/snapshot.test.mjs`
- `brain-map/tests/labels.test.mjs`
- `brain-map/tests/code-layer.test.mjs`

### 2. Browser Lifecycle Guard Tests

**File**: `brain-map/tests/browser-lifecycle.test.mjs` (new)

**Tests 1-6**: Guard tests that verify the three fixed test files complete without errors and don't hang during cleanup.

**Test 7**: Fast leak-regression check that detects orphaned chromium processes after tests run. This is a quick smoke test to catch future regressions in browser cleanup.

### 3. Clone Directory Cleanup Infrastructure

**Files modified**: `lib/cleanup_sweep.py`

**Problem**: Browser instances (Chromium/Playwright) create temporary clone directories for sandboxing (`.code_sign_clone*`). When processes crash, these directories persist and accumulate, wasting disk space.

**Solution**: Added a new sweep to find and remove orphaned clone directories.

#### New Constants
- `CLONE_SEARCH_ROOTS`: List of directories to search for orphaned clones
  - Always includes `tempfile.gettempdir()`
  - Also includes `$DARWIN_USER_CACHE_DIR` if set (macOS)

#### New Functions

**`_default_list_clone_dirs() -> list[dict]`**
- Lists all `.code_sign_clone*` directories under search roots
- Returns: path, size_bytes (calculated recursively), age_hours

**`_default_is_in_use(clone_dir: Path) -> bool`**
- Uses `lsof +D <dir>` to check if any process holds the directory open
- Fail-safe: returns True on any error (lsof not available, timeout, permission denied)
- This prevents accidental removal of in-use clones

**`_default_remove_clone_dir(clone_dir: Path) -> bool`**
- Removes a clone directory using `shutil.rmtree`
- Returns True if successful, False if removal fails

**`find_orphaned_clone_dirs(...) -> list[dict]`**
- Finds clones not currently in use
- Supports DI for testing

**`sweep_orphaned_clones(...) -> dict`**
- **Critical design**: Per-item recheck before removal
- For each clone:
  1. List all clones
  2. For each clone:
     - Recheck if it's in use (TOCTOU protection)
     - Remove if not in use
     - Skip if it became in use or removal failed
- Returns: {"removed": [...], "skipped": [...]}

#### Integration
- Wired into `run_daily_sweep()` as a new parameter set
- Integrated into `_write_log()` to report removed clones with size info
- Updated docstring and return value of `run_daily_sweep()`

### 4. Clone Cleanup Tests

**File**: `lib/tests/test_cleanup_sweep.py` (new tests 8-24 added)

**Tests 8-11**: `_default_list_clone_dirs()` functionality
- Lists clone dirs in temp roots
- Ignores non-matching directories
- Handles missing roots gracefully
- Calculates directory size correctly

**Tests 12-14**: `_default_is_in_use()` fail-safety
- Returns True if lsof is unavailable
- Returns True on timeout
- Calls lsof correctly with the directory

**Tests 15-17**: `_default_remove_clone_dir()` safety
- Removes directories successfully
- Fails gracefully if removal fails
- Handles nonexistent directories

**Tests 18-19**: `find_orphaned_clone_dirs()` filtering
- Finds unused clones
- Skips in-use clones

**Tests 20-22**: `sweep_orphaned_clones()` basic operation
- Removes clones that are still not in use after recheck
- Skips clones that become in-use between list and recheck
- Handles removal failures

**Tests 23-24**: TOCTOU (Time-of-Check-Time-of-Use) race condition protection
- **Test 23**: Demonstrates why naive single-upfront-check fails
  - A clone becomes in-use after the initial check
  - With single-check approach, it would be removed anyway (wrong!)
  - With per-item recheck, it's correctly skipped
  
- **Test 24**: Full scenario with multiple clones
  - Clone 1: becomes in-use during recheck (skipped)
  - Clone 2: already in-use (skipped)
  - Clone 3: orphaned (removed)
  - Proves the per-item recheck prevents accidental removal of in-use clones

## Key Design Decisions

### Per-Item Recheck Pattern
The critical difference from a naive approach is checking each clone again right before removal:

```python
for clone in list_clone_dirs():
    # Recheck: is it still in use right now?
    if is_in_use(clone["path"]):
        skip(clone)
        continue
    # Now safe to remove
    remove(clone)
```

This prevents TOCTOU races where a clone might become in-use between the initial list and removal.

### Fail-Safe Default
`_default_is_in_use()` returns True on any error (lsof unavailable, timeout, permission denied). This ensures that if we can't verify a clone is unused, we leave it alone rather than risk removing something in use.

### Size Reporting
Clone sizes are reported as "logical size, APFS clone" to be honest about what's being measured. Clone directories are sparse on APFS, so actual disk freed may be less than reported.

## Testing Strategy

**Manual Acceptance Criterion**: Run the full brain-map test suite twice locally.

The implementation includes:
- Automated unit tests (test_cleanup_sweep.py)
- Browser lifecycle guards (browser-lifecycle.test.mjs) 
- Integration with existing daily sweep

A human should run the complete test suite at least once locally to verify:
1. No regressions in existing tests
2. No new test failures
3. No unexpected browser process leaks

Command:
```bash
node --test brain-map/tests/*.test.mjs
~/.agents/venv/bin/python -m pytest lib/tests/test_cleanup_sweep.py -v
```

## Audit Notes (Step 9 from plan)

### Already Handled
- **Worktrees/.build cleanup**: Already handled by existing `drop_build_output()` in cleanup_sweep.py
- **Simulator state cleanup**: Already handled by `disk_reclaim.py`
- **Browser call sites**: Reviewed all major browser launch sites:
  - `lib/portfolio_*.py`: All close correctly (sync calls)
  - `lib/render_diagrams.py`: Closes correctly
  - `brain-map/render_map_images.py`: Closes correctly
  - `dashboard/scripts/capture_screenshot.mjs`: Uses explicit awaited finally block
  - `brain-map/gif-experiments/capture_brainmap*.py`: One-off dev scripts, not scheduled

### Out of Scope
- `brain-map/gif-experiments/*.py`: These are one-off developer scripts not run by any scheduled job

## Deployment Notes

The clone cleanup is safe to deploy:
- Fail-safe design (assumes "in use" on any check error)
- Per-item recheck prevents TOCTOU races
- Non-destructive: directories are regenerable by the next browser launch
- Logs all removals for visibility
