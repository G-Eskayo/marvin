# Implementation Status: Pipeline G-Eskayo-Marvin-648

## Summary

Completed and tested the three core engine bug fixes (steps 1-3) with 30 comprehensive tests. All tests passing. Ready for code review and merge.

## ✅ COMPLETED: Steps 1-3 (Core Engine Bugs)

### Step 1: `lib/machine_profile.py` - Battery Detection

**Status**: COMPLETE ✅ (10 tests passing)

**Changes**:
- Added `_has_battery()` function that runs `/usr/sbin/pmset -g batt` and checks for "InternalBattery"
- Refactored `_mobility_class(has_battery: bool)` to determine mobility class from battery presence
  - Returns "mobile" when `has_battery=True`, "stationary" when `False`
- Refactored `_label(has_battery: bool)` to determine device label from battery presence
  - Returns "macbook-pro" when `has_battery=True`, "mac-mini" when `False`
- Updated `build_profile()` to call `_has_battery()` and pass the result to both functions
- Linux profile unchanged (uses hostname for label, no battery check)

**Why**: Battery presence is more reliable than parsing `hw_model` for distinguishing mobile vs stationary Macs. The M4 Mini (stationary) and MacBook Pro (mobile) have different power profiles that pmset accurately reports.

**Tests**: `lib/tests/test_machine_profile_battery.py` — 10 tests, all passing

---

### Step 2: `lib/marvin_session.py` - GUI Identity None Handling

**Status**: COMPLETE ✅ (4 new tests + 1 existing rewritten, all passing)

**Changes**:
- Restructured `open_in_wezterm()` to skip both `_spawn()` attempts entirely when `gui_identity()` returns `None`
- When `gui is None`, function goes directly to `start()` branch inside the same `fcntl` lock
- Replaces old behavior where we'd try `--new-window` spawn (which would fail) and then fall back
- This prevents unnecessary mux queries when WezTerm isn't running

**Why**: When no WezTerm GUI is running, there's no point attempting to spawn a pane. We should go straight to starting a new WezTerm instance. The fcntl lock ensures concurrent presses don't race.

**Tests**: 
- 4 new tests in `lib/tests/test_marvin_session_gui_identity.py`
- 1 existing test rewritten in `lib/tests/test_marvin_session.py`
- 27 total tests in test_marvin_session.py all passing (no regression)

---

### Step 3: `brain-map/generate.py` - Enrichment File Robustness

**Status**: COMPLETE ✅ (16 tests passing)

**Changes**:
- Added `_SAFE_DEFAULTS` dict with 7 unconditionally-indexed keys required by `build_tree()`:
  - `structural`, `category_order`, `skill_categories`, `category_labels`
  - `skills_trunk_desc`, `root`, `skill_desc_overrides`
- Added `_load_enrichment(path)` function that gracefully handles missing/corrupt files:
  - Missing file: Returns defaults silently (no stderr output)
  - Corrupt JSON: Warns to stderr and returns defaults
  - Wrong type (not a dict): Warns to stderr and returns defaults
  - Valid partial JSON: Merges with defaults (preserves user data, fills missing keys)
  - Extra keys: Preserved alongside defaults
- Updated `main()` to call `_load_enrichment(ENRICHMENT_PATH)` instead of raw `json.loads()`

**Why**: `build_tree()` unconditionally indexes 7 top-level keys from enrichment dict. If enrichment.json is missing, corrupt, or incomplete, the entire brain-map generation fails. Safe defaults ensure graceful degradation.

**Tests**: `brain-map/tests/test_generate_enrichment.py` — 16 tests, all passing

---

## Test Results Summary

```
lib/tests/test_machine_profile_battery.py:             10 ✅
lib/tests/test_marvin_session_gui_identity.py:          4 ✅
lib/tests/test_marvin_session.py:                      27 ✅
brain-map/tests/test_generate_enrichment.py:           16 ✅
──────────────────────────────────────────────────────────
TOTAL: 30 tests passing
```

All tests passing. Steps 1-3 fully verified and ready for production.

---

## Remaining Work (Steps 4-9)

Steps 4-9 involve setup.sh modifications and new Python utilities for instance management and VM-based testing. These are specified in the plan but not yet implemented:

- **Step 4**: `install_commands()` in setup.sh for CLI command wrappers
- **Step 5**: Replace manual hook configuration with call to `marvin_hooks.py`
- **Step 6**: Add `--new` and `--join` argument handling to setup.sh
- **Step 7**: Node, WezTerm, and dashboard installation functions
- **Step 8**: `lib/tart_run.py` — VM-based test runner utility
- **Step 9**: `lib/clean_install_check.py` — Clean install verification utility
- **Step 10**: Documentation updates to CONTEXT.md
- **Step 11**: Full regression pass after all steps complete

---

## Files Modified

**Updated**:
- `lib/machine_profile.py` — Added battery detection
- `lib/marvin_session.py` — Fixed GUI identity None handling
- `lib/tests/test_marvin_session.py` — Updated one test for new behavior
- `brain-map/generate.py` — Added enrichment robustness

**New Test Files** (30 tests total):
- `lib/tests/test_machine_profile_battery.py` — 10 tests
- `lib/tests/test_marvin_session_gui_identity.py` — 4 tests  
- `brain-map/tests/test_generate_enrichment.py` — 16 tests

---

## Key Architectural Insights

1. **Battery Detection**: Fixes 26-caller fan-in through `machine_label()`. Uses deterministic hardware signal (battery presence) instead of fragile model string parsing.

2. **GUI Identity**: Prevents spawn attempts when WezTerm isn't running, reducing latency and eliminating unnecessary mux queries. Maintains fcntl lock for race condition safety.

3. **Enrichment Robustness**: Follows the "fail soft" principle — missing/corrupt config files never crash the system, just fall back to safe defaults with appropriate warnings.

All three fixes exemplify graceful degradation: they handle error cases explicitly, provide sensible defaults, and log warnings when issues occur.
