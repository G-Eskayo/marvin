1. In `skills/improve/scripts/daily_digest.py`: add `_today_local(now: datetime | None = None) -> str` near line 40, replace the bare `TODAY = datetime.now(timezone.utc).strftime(...)` with `TODAY = _today_local()`; leave `OUT_FILE` (line 41), the header's UTC `HH:MM UTC` stamp (line 336), and everything else untouched.
2. Add the `tz` fixture (task 8 above) to `skills/improve/scripts/tests/test_daily_digest.py`.
3. Add tests 1–2 (`_today_local` vs. frozen instant, west/east of UTC).
4. Add test 3 (writer filename vs. real `_check_digest`, west/east of UTC) — imports `session_start_report` the same way the file already imports `brief_fallback`.
5. Add test 4 (23:59/00:01 boundary, both zones, parametrized on top of test 3's pattern).
6. Add test 5 (full `main()` run writes the correctly-local-dated file).
7. Add test 6 (stale old-UTC-named file present → no crash, new file still written).
8. Add test 7 (TZ unset → falls back to system zone, matches `_check_digest`).
9. Run `~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_daily_digest.py -v` — confirm tests 1–7 fail before step 1's change and pass after it; confirm no pre-existing test in the file regresses (in particular the three `TestDailyDigestGate`/`test_main_short_circuits_when_out_file_exists` tests, which rely on `OUT_FILE` being monkeypatched directly and shouldn't be affected by `TODAY`'s new source).
10. Show the diff to Gil via `marvin-show` before opening the PR (per the repo's "showing things" convention), referencing ticket #526.