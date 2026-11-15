# Redaction & Fading Message Implementation - Pipeline #829

## Summary
Complete implementation of sensitive information redaction and auto-fading message UI pattern across the MARVIN dashboard.

## Files Created

### Libraries
- `dashboard/src/lib/redact.js` - Core redaction utility supporting:
  - Home paths (macOS, Linux, Windows) → `~`
  - IPv4/IPv6 addresses with duration-text false-positive guard
  - Tailscale IPs → `(device)` placeholders
  - Registry-based device name resolution
  - Doc path redaction (`docs/plans/` and `handoff-*` patterns)

- `dashboard/src/lib/fading_message.js` - Message fade factory:
  - `createFadingMessage()` - returns scheduler function
  - `MESSAGE_FADE_MS` - 4s auto-clear duration
  - Timeout management for React components

### Test Files (TDD - tests written first)
- `dashboard/test/redact.test.js` - 30+ test cases
  - Home path redaction (cross-platform)
  - IPv4/IPv6 redaction with false-positive guards
  - Registry-based device name mapping
  - Edge cases (null, empty, special chars)
  - Idempotence verification

- `dashboard/test/fading_message.test.js` - 6 test cases
  - Exact MESSAGE_FADE_MS timing
  - Timeout cancellation/re-trigger
  - Unmount cleanup

- `dashboard/test/marvin_button.test.js` - 7 test cases
  - `composeOpenMessage(result)` pure function
  - Directory redaction in messages
  - Error handling

- `dashboard/test/boot_data.test.js` - Extended with 5 redaction tests
  - Details in check text redaction
  - Handoff filename slug removal
  - Disk/job count preservation (no false redaction)

## Files Modified

### Components
- `dashboard/src/components/MarvinButton.jsx`
  - Extracted `composeOpenMessage(result)` as named export
  - Integrated fading message with timeout management
  - Cleanup on unmount via useEffect

- `dashboard/src/components/HealthDashboard.jsx`
  - Redacts `CheckCard` detail display

- `dashboard/src/components/HealthDrilldown.jsx`
  - Redacts detail panel output

- `dashboard/src/components/ActivityBanner.jsx`
  - Redacts red-check detail display

- `dashboard/src/components/PortfolioHub.jsx`
  - Updated `OpenDevSiteButton` with fading message (Decision: "Do both now")

### Core
- `dashboard/electron/main/boot_data.js`
  - Updated `syncLine()` to redact extracted text
  - Updated `deviceReason()` to redact fallback message
  - Updated `handoffLine()` to show date only (no descriptive slug)
  - Added registry parameter threading

## Design Decision Resolved
✅ **fade-scope**: Chose "Do both now" - fading message pattern applied to both:
  - MarvinButton (MARVIN session messages)
  - PortfolioHub.OpenDevSiteButton (dev site messages)

This ensures consistent UX across header button status displays and maximizes reusability of `createFadingMessage` helper.

## Testing Strategy
- All tests use vitest with fake timers for deterministic async behavior
- Boot_data tests use temporary filesystem fixtures (no real ~/.claude modified)
- Component tests extract pure functions (`composeOpenMessage`) for unit testability
- Redaction tests include edge cases: null/undefined, case-insensitivity, performance (large input)

## Next Steps (Manual Verification)
1. Run full dashboard test suite: `npm -C dashboard test -- --run`
2. Take screenshots via `marvin-show`:
   - 900px viewport: MARVIN button message fade (visible→4s→hidden)
   - 1440px viewport: Health tab with redacted check detail in drilldown
3. Verify no visual regressions in other dashboard tabs

## Key Design Patterns Used
- **Pure function extraction** for testability (`composeOpenMessage`)
- **Injectable timer pattern** for fake-timer testing (from `createTriggerHub`)
- **Structural regex matching** for redaction (not blocklist-based)
- **Cross-process import** to share redaction between main and renderer (both use `redactText`)
- **Registry-based device mapping** for multi-machine setups
