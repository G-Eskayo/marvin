# Feature Gate Implementation Status (marvin#647)

## Completed and Tested ✅

### Core Library (lib/)
- **addon_migrate.py**: Migration script to enable all known add-ons for backward compatibility
  - 13 tests passing (idempotent, handles corrupt configs, preserves manual choices)
  - CLI interface: `~/.agents/venv/bin/python lib/addon_migrate.py --instance-dir <path>`
  - Reuses `lib/instance.py`'s `instance_dir()` and handles all edge cases

- **seal_beta_ingest.py**: Feature gate implemented at job entry point
  - Function signature: `ingest(..., feature_enabled=None)` accepts injectable feature checker
  - Default: `lambda name: True` for backward compatibility with existing tests
  - Production: Pass `inst.feature_enabled` to honor real feature gate
  - Returns `{"ok": True, "skipped": "feature_off", ...}` when gate is off
  - 5 new feature gate tests passing (items 2–6 from design doc)
  - 48 existing tests still passing (no regression)
  - Module docstring updated with feature gate description

### Resume Tailor Skill
- **check_enabled.py**: Gate script at `skills/resume-tailor/scripts/check_enabled.py`
  - Exits 0 if resume_tailor is enabled, 1 if off or instance missing
  - Never writes anything (read-only check)
  - 6 tests passing (on/off/missing/corrupt configs, read-only verification)
  - Usage: `~/.agents/venv/bin/python ~/.agents/skills/resume-tailor/scripts/check_enabled.py`

- **SKILL.md**: Phase 0 gate added to command routing
  - Runs check script before any command handler
  - Returns user-friendly message directing to dashboard or manual instance.json edit if off

### Dashboard (Partial)
- **AddonNotSetUp.jsx**: Shared React component for all three add-ons
  - Renders add-on name/description, enable button, manual setup instructions
  - Single component reused by all add-ons (zero per-add-on duplication)
  - Located at `dashboard/src/components/AddonNotSetUp.jsx`

## Blocked / Manual Completion Required ⚠️

### Dashboard Instance Handler
**File**: `dashboard/electron/main/instance.js`
**Status**: Code written but Write tool refusing to create file in this directory

```javascript
// Required handlers:
// - ipcMain.handle('instance:features', async () => { ... })
//   Returns { portfolio, resume_tailor, seal_ingest } booleans
// - ipcMain.handle('instance:setFeature', async (_e, name, value) => { ... })
//   Validates name against KNOWN_ADDONS, safely reads/writes instance.json
```

**Action Required**: Manually create the file or use a different tool to create the JavaScript handler.

### Dashboard Preload Wiring
**File**: `dashboard/electron/preload/index.js`
**Change**: Add instance methods to contextBridge API
```javascript
instance: {
  features: () => ipcRenderer.invoke('instance:features'),
  setFeature: (name, value) => ipcRenderer.invoke('instance:setFeature', name, value)
}
```

### Dashboard Tab Gating
**File**: `dashboard/src/tabs/PortfolioHub.jsx` or wrapper component
**Change**: Wrap component with feature gate check
- Fetch `instance.features()` on mount
- Render `AddonNotSetUp` if `portfolio` is False
- Render real component if True

### Post-Merge Step
**Required once PR is merged**:
```bash
~/.agents/venv/bin/python lib/addon_migrate.py
```
This one-time step ensures Gil's existing add-ons remain enabled when the gate ships.

## Test Results Summary

```
lib/tests/test_addon_migrate.py ........................ 13 PASSED
lib/tests/test_seal_beta_ingest.py ..................... 53 PASSED
  (5 new feature gate tests + 48 existing regression tests)
lib/tests/test_instance.py ............................. 26 PASSED
skills/resume-tailor/scripts/tests/test_check_enabled.py  6 PASSED

TOTAL: 98 tests passing
```

## Design Decisions Applied

- **tab_shape**: Option C - Only Portfolio's existing tab gets the not-set-up gate now
- **setup_button**: Option A - Direct write to `instance.json` via IPC

## Backward Compatibility

All existing code paths continue to work:
- `lib/seal_beta_ingest.py:ingest()` defaults to feature enabled (backward compatible)
- Production calls must pass `inst.feature_enabled` to activate the real gate
- `lib/instance.py:feature_enabled()` unchanged; returns False for missing/not-explicitly-true features
- Resume Tailor skill works normally when feature not explicitly gated

## Next Steps for Manual Completion

1. Create `dashboard/electron/main/instance.js` with handlers
2. Wire handlers into `dashboard/electron/main/index.js:createInstanceHandlers()`
3. Export handlers in `dashboard/electron/preload/index.js`
4. Gate Portfolio tab mount with feature check
5. Run `lib/addon_migrate.py` after PR merge
6. Run dashboard tests: `cd dashboard && npm test`
