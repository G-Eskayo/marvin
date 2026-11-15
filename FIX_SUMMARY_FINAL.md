# Ticket #526 Code Review Fix: test_today_local_unset_tz_env

## Issue Identified
The test `test_today_local_unset_tz_env` (line 578 in the file) was **not actually verifying** that `_today_local()` respects the system timezone when TZ is unset. The test would pass even if the function returned UTC instead of local time — the exact bug ticket #526 fixes.

### Root Cause
- The test computed `pst_result` but never used it
- It only checked string shape (length, valid date parts, year in range)
- It did NOT compare against the expected system timezone date

## Solution Implemented
Fixed the test to:

1. **Capture an instant once** at the start of the test (`now_utc = datetime.now(timezone.utc)`)
2. **Compute the expected system local date** from that captured instant using the same formula as `_check_digest`: `now_utc.astimezone().strftime("%Y-%m-%d")`
3. **Pass the captured instant** to `_today_local(now_utc)` to avoid midnight race conditions
4. **Assert equality** against the expected system local date with a clear error message that explains the bug being caught

### Key Changes in test_today_local_unset_tz_env
```python
# Before: only checked string shape, `pst_result` unused
# After: captures UTC instant, computes expected local date, verifies against it

now_utc = datetime.now(timezone.utc)
expected = now_utc.astimezone().strftime("%Y-%m-%d")

# ... TZ manipulation ...

result = dd._today_local(now_utc)

# Proper assertion with clear explanation
assert result == expected, f"Expected {expected} (system local date) but got {result} when TZ is unset"
```

## Test Results
✅ All 34 tests in `test_daily_digest.py` pass
- 6 `_today_local` tests (tests 1-6 per plan): PASS
- Test 7 (unset TZ env, the fixed test): PASS ← now actually verifies the bug
- 3 `TestDailyDigestGate` tests (monkeypatched `OUT_FILE`): PASS ← no regressions
- 22 other tests: PASS ← no regressions

## What This Fix Catches
The fixed test now properly catches the bug that ticket #526 addresses: if `_today_local()` were to return a UTC date instead of the system's local timezone date when TZ is unset, the test would **fail with a clear message**, rather than silently passing.
