# Timezone Test Fixes for Ticket #526

## Summary
Fixed three must-fix defects in `skills/improve/scripts/tests/test_daily_digest.py` identified by code review. All tests now properly verify timezone handling.

## Changes Made

### 1. Added `tz` Fixture (lines 380-403)
- Properly sets and restores TZ environment variable with `time.tzset()` cleanup
- Provides `set_tz(zone)` and `clear_tz()` methods
- Includes teardown to restore original TZ

**Why:** TZ environment changes don't take effect without `time.tzset()` call, so tests were testing nothing.

### 2. Fixed `test_today_local_with_utc_datetime` (lines 516-528)
- **Was:** Only checked format prefix "2026-10-", didn't verify actual conversion
- **Now:** Uses instant where UTC and local dates differ (07:30 UTC Nov 13 → 23:30 PST Nov 12)
- Asserts result == "2026-11-12" to verify conversion happened

### 3. Fixed `test_today_local_west_of_utc` (lines 531-541)
- **Was:** Passed local PDT datetime directly, tested nothing about conversion
- **Now:** Passes UTC datetime and verifies it converts to correct local date
- Uses PST8PDT zone (UTC-8) where local date is previous day

### 4. Fixed `test_today_local_east_of_utc` (lines 544-554)
- **Was:** Passed local JST datetime, used instant that didn't cross date boundary
- **Now:** Uses 20:00 UTC on Nov 12 → 05:00 JST on Nov 13 (next day)
- Asserts result == "2026-11-13" to verify conversion

### 5. Fixed `test_today_local_unset_tz_env` (lines 568-585)
- **Was:** Only checked format, never called `time.tzset()` so test was inert
- **Now:** Sets TZ to PST, then clears it and calls `time.tzset()`
- Verifies function works correctly when TZ is unset

## Test Results

All 34 tests pass:
```
✓ test_today_local_with_utc_datetime
✓ test_today_local_west_of_utc
✓ test_today_local_east_of_utc
✓ test_today_local_unset_tz_env
+ 30 existing tests (no regressions)
```

## Key Insight

The tests now actually verify timezone conversion by:
1. Using instants where UTC and local dates differ (not same day in both zones)
2. Setting TZ environment variable with proper `time.tzset()` cleanup
3. Asserting specific expected dates, not just format validation
