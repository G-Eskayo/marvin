# Ticket #189 Cleanup: PR Audit Section

## Summary

This PR completes ticket #189 (browser lifecycle management and orphaned clone cleanup). It fixes three issues from prior attempts:

1. **Browser launch patterns**: Three test files were using `chromium.launch()` without `channel: 'chrome'`, breaking against `playwright-core` (which has no bundled browser). Fixed with proper comments justifying the real-Chrome requirement.

2. **Orphaned clone directory sweep**: Rewritten to correctly handle the `*.code_sign_clone` parent / `code_sign_clone.*` child directory structure, with proper lsof return-code handling and age-based filtering (min 1 hour old before removal).

3. **Test suite corrections**: Fixed three broken mocks (side_effect usage), added per-item recheck TOCTOU safety verification, added min_age_hours tests, and verified all acceptance criteria.

## Real Browser Launch Sites (Verified via grep)

The codebase was audited to find all `chromium.launch(` calls and verify they are correct. The previous attempt's audit only inspected 4 files and found ~30 false-positive hits on `marvin_launcher.launch()` (Claude subagent spawns, completely unrelated to browsers).

**Verified real browser-launch sites (8 total):**

1. ✅ **brain-map/tests/snapshot.test.mjs:33** — Uses `{ channel: 'chrome' }`, properly commented. Real Chrome required.
2. ✅ **brain-map/tests/labels.test.mjs:35** — Uses `{ channel: 'chrome' }`, properly commented. Real Chrome required.
3. ✅ **brain-map/tests/code-layer.test.mjs:30** — Uses `{ channel: 'chrome' }`, properly commented. Real Chrome required.
4. ✅ **dashboard/scripts/capture_screenshot.mjs** — Clean: `finally { await browser.close() }` with proper await.
5. ✅ **brain-map/render_map_images.py** — Clean: `async with`-based closure, properly awaited.
6. ✅ **lib/render_diagrams.py** — Bundled Chromium only (mechanism doesn't apply to real Chrome).
7. ✅ **lib/portfolio_parity.py** — Bundled Chromium only (mechanism doesn't apply).
8. ✅ **lib/portfolio_inventory.py** — Bundled Chromium only (mechanism doesn't apply).
9. ⚠️ **brain-map/gif-experiments/capture_brainmap*.py** — Clean, out-of-scope dev scripts.
10. ✅ **tools/browser/browser_ctl.py** — Intentional persistent-daemon CDP connection (not a per-run launch, different mechanism).

**False-positive clarification:**

The ~30 remaining `*.launch(` grep hits are `marvin_launcher.launch()` calls (Claude-agent subagent spawning, not browser launches) across lib/*.py. These were the source of confusion in the prior audit — worth documenting so the next reader doesn't re-walk that trail.

## Acceptance Criteria (All Met)

1. ✅ **Guard tests 1–6**: Verify three test files close browsers correctly. Tests spawn each file independently and confirm exit code 0.

2. ✅ **Guard tests 4–6 (timeout variant)**: Same tests with 60-second timeout to catch hanging cleanup. Tests pass without hanging.

3. ✅ **Test 7 (leak regression)**: Real-browser process count check before/after a test run. Confirms zero leaked chromium processes.

4. ✅ **Clone directory structure**: Rewrote `_default_list_clone_dirs()` to glob `*.code_sign_clone` parents, then `code_sign_clone.*` children within each parent.

5. ✅ **lsof return-code semantics**: Fixed `_default_is_in_use()` to treat:
   - returncode == 0 → in use (processes found)
   - returncode == 1 → not in use (nothing found)
   - anything else → fail-safe: assume in use

6. ✅ **Age filtering**: Added `min_age_hours` parameter (default 1.0) to `find_orphaned_clone_dirs()` and `sweep_orphaned_clones()`. Clones younger than 1 hour are never considered for removal.

7. ✅ **Per-item recheck (TOCTOU safety)**: `sweep_orphaned_clones()` calls `is_in_use(path)` immediately before removal for each clone. Protects against a process starting to use a clone between the initial list and the removal attempt.

8. ✅ **Human-readable log output**: `_write_log()` now formats clone dir sizes as MB/GB instead of raw bytes. Uses `_format_bytes()` helper.

9. ✅ **Module docstring**: Updated to describe corrected parent/child clone structure, age filtering, and per-item recheck mechanism.

10. ✅ **Test suite**: Fixed three broken mocks (side_effect usage), added tests 25–26 for min_age_hours filtering and recheck behavior.

## Test Results

Local test execution confirms:

- **brain-map/tests/browser-lifecycle.test.mjs**: All 7 tests pass (guard tests 1–6 + leak-regression test 7).
- **lib/tests/test_cleanup_sweep.py**: All 26 tests pass, including:
  - Tests 8–11: List clone dirs functionality
  - Tests 12–14: is_in_use fail-safe behavior (fixed mocks)
  - Tests 15–17: Remove clone dir edge cases
  - Tests 18–19: Find orphaned clones
  - Tests 20–24: Sweep with per-item recheck and TOCTOU race scenarios
  - Tests 25–26: min_age_hours filtering

## Files Modified

1. **brain-map/tests/snapshot.test.mjs** — Added `{ channel: 'chrome' }` and justifying comment
2. **brain-map/tests/labels.test.mjs** — Added `{ channel: 'chrome' }` and justifying comment
3. **brain-map/tests/code-layer.test.mjs** — Added `{ channel: 'chrome' }` and justifying comment
4. **lib/cleanup_sweep.py** — Rewrote `_default_list_clone_dirs()`, fixed `_default_is_in_use()`, added min_age_hours throughout, added `_format_bytes()`, updated module docstring
5. **lib/tests/test_cleanup_sweep.py** — Fixed three broken mocks, added tests 25–26

## Files to Delete (Manual Step)

The following stale design docs from prior attempts should be deleted before merge:
- `docs/design/browser-lifecycle-cleanup-189.md`
- `docs/design/pipeline-g-eskayo-marvin-415.md`
- `docs/design/pipeline-g-eskayo-marvin-415-tasks.md`

These contain superseded analysis and implementation plans.

## Notes

- The browser-lifecycle guard tests use node's native `--test` runner with spawn, avoiding the 1200s timeout issue from prior attempts (which tried to chain 6+ full browser launches in one test process).
- The leak-regression test (test 7) is lightweight: runs one test file, counts chromium processes before/after, confirms zero increase.
- The sweep's per-item recheck is critical for production safety — a process could start using a clone between the initial list and removal attempt (demonstrated in test 21).
