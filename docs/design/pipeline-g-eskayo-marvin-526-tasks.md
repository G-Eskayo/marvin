1. `skills/improve/scripts/daily_digest.py`: import `date` from `datetime` (alongside existing `datetime, timedelta, timezone`), change line 40 to `TODAY = date.today().isoformat()`. Leave the header's `HH:MM UTC` stamp (line 336) untouched.
2. Add the frozen-time/TZ-simulation helper fixture in `skills/improve/scripts/tests/test_daily_digest.py` (sets `TZ` + `time.tzset()` + monkeypatches `time.time`, reloads `dd`, restores on teardown).
3. Write and pass test 1 (exact AC scenario: 2026-11-12 23:30 local UTC-8 → `2026-11-12.md`).
4. Write and pass test 2 (writer/reader agreement, UTC-8 and UTC+9, parametrized).
5. Write and pass test 4 (midnight-boundary ×2-zones, parametrized).
6. Write and pass test 5 (stale old-UTC-named leftover file present → no crash, new file written).
7. Write and pass test 6 (TZ unset → falls back to system zone, still agrees with reader).
8. Confirm test 3 (temp HOME only) and test 8 (existing suite green) by running the full `test_daily_digest.py` file.
9. Resolve the `probe` Decision above with the owner; if **A**, open the follow-up ticket for the logging+probe; if **B**, implement the logging in `lib/session_start_report.py`, add the probe function + `PROBES` entry in `lib/purpose_metrics.py`, and update issue #526's `Recurrence check` → `Probe:` field via `gh issue edit` to the new registered name.
10. Run the full `skills/improve/scripts/tests/test_daily_digest.py` suite plus `lib/tests/test_brief_fallback.py` and `lib/tests/test_session_start_report*.py` (no functional change there, but they share the local-date convention this fix now matches) to confirm nothing else regresses.