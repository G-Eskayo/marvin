## North-star fit

**Reuses:** `cross_machine_merge.py:68`'s exact formula, `TODAY = date.today().isoformat()` — the writer should compute "today" the same way its readers (`cross_machine_merge.py:68`, `session_start_report.py:396` `_check_digest`) already do. I'm wrapping that one-liner in a tiny seam function rather than leaving it as a bare module-level expression, for a reason specific to this ticket: the fix is otherwise untestable without a real sleep-until-midnight or a new `freezegun` dependency, and this repo has already decided against adding `freezegun` (`docs/design/pipeline-g-eskayo-marvin-488.md:10`: "no `freezegun` dependency added" — plain `monkeypatch` on `datetime` is "already the project's standard mocking tool"). `session_start_report.py:51` (`_now()`) is the established precedent for exactly this kind of seam: a one-line wrapper around `datetime.now(timezone.utc)` that tests monkeypatch wholesale. I'm extending that pattern by one parameter (`now: datetime | None = None`) so the *instant* is injectable too, not just swappable — because this bug only reproduces near local midnight, and a test that runs at an arbitrary real time would almost never hit that window.

**Simplest sufficient approach:** one function (`_today_local`) replacing one bare assignment; no new file, no new dependency, no change to any reader (verified below — all three already use local date). Tests drive the real `date`/`datetime` local-time conversion through `os.environ["TZ"]` + `time.tzset()` (POSIX, works on Darwin) rather than mocking it away, so the test exercises the actual libc-backed local-time path the ticket is about, not a stand-in for it.

**Tokens/compute:** negligible — same one string computation, run once at import, as today. No runtime cost change.

**Phone-OS direction:** not directly — this is a correctness/robustness fix (north star 5: every machine's digest agrees regardless of its time zone), not phone-OS-shaped work.

**User capability:** more capable — fixes a silent, latent failure mode (a missing digest line, a skipped run) the user would otherwise have to notice and debug themselves; no behavior is being automated away from them.

**Machine:** runs wherever `daily_digest.py` already runs (any machine, via launchd or manual run) — no machine-placement decision needed, this is a pure library fix.

## Verified against the ticket's claims

- `cross_machine_merge.py:68`: `TODAY = date.today().isoformat()` — local date. ✅
- `session_start_report.py:396` (`_check_digest`): `today = _now().astimezone().strftime("%Y-%m-%d")` where `_now()` (line 51–52) returns `datetime.now(timezone.utc)` — `.astimezone()` with no argument converts to the system's local zone, i.e. local date. ✅ (equivalent formula to `date.today()` for the same instant.)
- `research_digest.py` (lines 55, 71, 100): `today = date.today().isoformat()` — local date, and it's a separate digest with its own naming, not a reader of `daily_digest.py`'s output, exactly as the ticket says. ✅
- `daily_digest.py:40`: `TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")` — the lone UTC outlier. ✅ Confirms the ticket's diagnosis exactly; no readers need changing.

## Design decision (made, not punted to Gil)

Ticket's literal "What to build" says change line 40 to a bare `TODAY = date.today().isoformat()`. I'm implementing the same formula but behind a seam function instead of leaving it a bare module-level expression:

```python
def _today_local(now: datetime | None = None) -> str:
    """Local calendar date — same formula cross_machine_merge.py:68 and
    session_start_report._check_digest use, so writer and readers always agree."""
    return (now or datetime.now(timezone.utc)).astimezone().date().isoformat()

TODAY = _today_local()
OUT_FILE = DIGEST_DIR / f"{TODAY}.md"
```

This is a pure implementation-detail call (how to make the fix testable), not a product/UX choice, so it doesn't need a Decisions section — I'm stating it here per the ambiguity-resolution instruction. No other file changes.

## Tests to write FIRST (`skills/improve/scripts/tests/test_daily_digest.py`)

All new tests go in the existing file, using its established conventions (`monkeypatch.setattr(dd, ...)`, `tmp_path`, the autouse `_pinned_machine_role` fixture already pinning `brief_fallback.should_run`/`is_primary`). None touch the real `~/.claude`.

1. **`test_today_local_matches_check_digest_formula_west_of_utc`** — freeze instant `2026-11-13T07:30:00Z`, set `TZ=Etc/GMT+8` (UTC-8) + `time.tzset()`. Assert `dd._today_local(frozen)` == `"2026-11-12"`. Covers acceptance criterion 1 exactly (23:30 local Nov 12 / 07:30 UTC Nov 13 → `2026-11-12`).
2. **`test_today_local_matches_check_digest_formula_east_of_utc`** — same frozen instant, `TZ=Etc/GMT-9` (UTC+9). Assert `dd._today_local(frozen)` == `"2026-11-13"`.
3. **`test_writer_filename_matches_reader_lookup_west_and_east_of_utc`** (parametrized over the two zones above) — for each zone: compute `writer_date = dd._today_local(frozen)`, write a file at `digest_dir / f"{writer_date}.md"`, monkeypatch `session_start_report._now` to return the same frozen instant, call the real `session_start_report._check_digest("today's daily digest", digest_dir)`, and assert it is non-`None` (i.e. it found exactly the file the writer named). This is the direct "writer's filename equals the date `_check_digest` looks for" assertion from acceptance criterion 2, run against the real reader function, not a reimplemented formula.
4. **`test_today_local_agrees_at_2359_and_0001_both_zones`** (parametrized, 4 cases: {UTC-8, UTC+9} × {23:59, 00:01} local) — same pattern as test 3, covering "How we'll try to break it" bullet 1 directly.
5. **`test_main_writes_local_dated_file_for_frozen_midnight_crossing`** — full `main()` run: `TZ=Etc/GMT+8`, monkeypatch `dd.OUT_FILE` to `digest_dir / f"{dd._today_local(frozen)}.md"` and `dd.DIGEST_DIR` to `digest_dir`, stub `dd.roadmap_summary`/`dd.recent_handoffs_summary`/`dd.qa_kb_summary`/`dd.bench_summary`/`dd.improvement_queue_summary`/`dd.reviewer_health_summary` to cheap literals and `dd.call_claude` to a literal (same stubbing style as the existing raise-on-call sentinels, just returning values instead of raising), then call `dd.main()` and assert `(digest_dir / "2026-11-12.md").exists()`. This is acceptance criterion 1's literal claim ("the digest file written is `2026-11-12.md`"), exercised end-to-end.
6. **`test_main_tolerates_stale_file_under_old_utc_name`** — pre-create `digest_dir / "<old-UTC-dated-name>.md"` (a date that is *not* the computed local date) with arbitrary content before running `main()` with the same stubs as test 5; assert `main()` completes without raising, the new local-dated file is written, and the stale file is left untouched (not deleted/corrupted). Covers "How we'll try to break it" bullet 2 — "still skips cleanly, no crash" read as "completes without raising"; ticket's own note says a duplicate is expected and acceptable on the switch day.
7. **`test_today_local_falls_back_to_system_zone_when_tz_unset`** — `monkeypatch.delenv("TZ", raising=False)` + `time.tzset()` (restores whatever the real system zone is), then assert `dd._today_local()` (no frozen instant — real now) equals `date.today().isoformat()` computed independently in the test body, and separately that it agrees with `datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")` (the `_check_digest` formula) for a real "now" captured once up front to avoid a midnight race in the test itself. Covers "TZ unset... falls back to the system zone, same as the readers."
8. A small **`tz` fixture** used by tests 1–4 and 7: saves `os.environ.get("TZ")` before the test, exposes a `set(tz_name)` helper that does `monkeypatch.setenv`/`delenv` + `time.tzset()`, and on teardown restores the original `TZ` value and calls `time.tzset()` again — so no other test in the (sequential, non-xdist) suite observes a mutated process timezone. Not a test itself, but required infrastructure; counted here because getting its teardown right is what keeps the other tests safe to run in any order.

All of 1–7 fail today against the current `datetime.now(timezone.utc)` line (no `_today_local` exists yet, and the UTC-only formula disagrees with `_check_digest`'s local-date formula at the frozen instants chosen) — satisfying "verify fails when code changes without a test changing."

## Out of scope (flagged, not silently dropped)

- The "Recurrence check" section's probe ("count days where session-start found no daily digest while an adjacent-date digest exists") is **not** in the Acceptance Criteria checklist, only in the backlog-tracking metadata (checked 2026-11-26). I'm treating it as a separate follow-up rather than part of this PR's required diff — flagging this explicitly rather than quietly skipping it.
- `cross_machine_merge.py`, `session_start_report.py`, `research_digest.py` get no code changes — confirmed above they're already correct.

## Task List

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