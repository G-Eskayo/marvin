I now have everything needed to write the plan.

## North-star fit

**Reuses before adding anything new:** `skills/improve/scripts/tests/test_daily_digest.py:395-407`'s `mock_produced` call-counting stub (already proven to isolate `brief_fallback.produced()` from the real network in exactly this TOCTOU shape) is the pattern `test_build_idempotency_with_fallback_gate` should have used and didn't — that's must-fix #1. All four must-fix items are pure test-isolation bugs in code that is *already correct*: `lib/morning_brief.py` and `lib/health_checks.py` already carry every production fix from the last revision (`BRIEF_USUAL_HOUR/MINUTE/GRACE_MINUTES` constants, `check_brief_builder(now=...)`, `builder_of(now=...)` calling `_day()`) — I re-read both files directly and confirmed this, so no production code changes are needed this round, only test fixes. The one new piece of infrastructure — a shared `utc_tz` pytest fixture — generalizes a pattern four tests in `test_health_checks.py` already use ad hoc (`monkeypatch.setenv("TZ", "UTC")` + `time.tzset()`) into one correctly-ordered place, rather than hand-rolling the restore four more times (`feedback-composability-principle`, `feedback-check-for-reuse-before-building`).

**Why this is the simplest sufficient approach:** every defect in the must-fix list is a missing or wrong test double, not a design gap — so the fix is narrowly test-only. No new abstraction, no new file beyond one fixture added to the existing `lib/tests/conftest.py` (which already holds exactly this kind of suite-wide test-isolation fixture, e.g. `_no_real_github`, `_no_du_on_the_real_home` at lines 61–83).

**Where this spends/saves tokens:** spends nothing beyond editing ~5 test functions and adding one ~12-line fixture; it doesn't touch render/build logic. It prevents a second class of cost: a test suite that silently SSHes to the real Mini or trips over host timezone is a flaky/slow suite that burns tokens on re-runs and false signals every time CI runs somewhere other than Gil's exact timezone.

**More capable or more passive:** more capable — this closes the gap between "tests pass on this machine today" and "tests are actually deterministic," which is the precondition for the merge gate (and future CI on `mac-mini-2012`, ADR 0069) to be trusted at all.

## What's already correct vs. what's still broken

Verified directly (not from the prior doc's self-description):

- `lib/morning_brief.py:30-32,297,356-366` — `BRIEF_USUAL_HOUR/MINUTE/GRACE_MINUTES`, `build()` using them, `builder_of(now=...)` calling `_day(now or datetime.now(timezone.utc))` — **all present and correct**.
- `lib/health_checks.py:750-771` — `check_brief_builder(now=...)` reads `mb.BRIEF_USUAL_HOUR/MINUTE/GRACE_MINUTES` and passes `now` through — **correct**.
- `CONTEXT.md`'s "Brief owner" bullet — **already corrected**, matches ADR 0067 and the real state of `cross_machine_merge.py`.
- `lib/health_checks.py::JOB_PLACEMENT` (AC1), the three `-fallback` plists, `daily_digest.py`/`research_digest.py`/`run_colony.py` wiring to `should_run()`/`produced()` (AC2/AC3) — **all present**, confirmed by reading each file.
- Still broken, confirmed by reading the exact lines and running the tests:
  1. `lib/tests/test_morning_brief.py:131-166` (`test_build_idempotency_with_fallback_gate`) mocks only `brief_fallback.should_run`; both `build()`'s pre-check and its TOCTOU recheck call the real `brief_fallback.produced()`, which (since `tmp_path` isn't under `$HOME`) falls through `_infer_remote_path` to `$HOME/.claude/<name>` and does a real, live SSH via `machine_profile.remote_devices()`. Confirmed by reading `produced()`/`read_remote()` end to end; it runs fast on this sandboxed machine only because `remote_devices()` is empty here — on a real machine with a populated registry it would block on a live SSH round-trip to the Mini.
  2. `lib/tests/test_health_checks.py:1291-1374` — all four `check_brief_builder` tests do `monkeypatch.setenv("TZ", "UTC"); time.tzset()` and never call `time.tzset()` again after monkeypatch restores `TZ` at teardown. Confirmed: no fixture, no `finally`, nothing restores the C-level zone, so every test after these in the same process run under UTC.
  3. `lib/tests/test_brief_fallback.py:69-82` (`test_past_deadline_before`) — unused `import pytz` (ImportError risk if not installed), and the `if hasattr(datetime.now(), 'astimezone')` guard is always true, hiding that the real content of the test is host-timezone-dependent.
  4. `lib/tests/test_brief_fallback.py:110-124` (`test_should_run_standby_before_deadline`) — fixes `now` at 08:00 UTC with no `run=` mock. `past_deadline()` converts via `.astimezone()` to **local** time before comparing against `08:30`; on a host at UTC+2 or later, local time is already ≥ 08:30+60m, so the function falls through past the "before deadline" branch straight into the real, unmocked `produced(local_path, remote_path, run=run)` → real SSH. (`test_should_run_primary` at line 102-106, also named in the finding, is actually host-independent — it passes `device_id` explicitly so `is_primary()` is a pure prefix check and the function returns before ever reaching `produced()`; I'll still route it through the same `utc_tz` fixture for consistency, but it has no real bug.)
  5. Confirmed still pre-existing, out of scope: `lib/tests/test_no_hardcoded_home.py::test_no_code_hard_codes_the_mac_home_directory` fails on `HEAD` today (`docs/screenshots/vitals-v4/data.js` hard-codes `/Users/gileskayo` and isn't in that test's `ALLOWED` set) — unrelated to this ticket's diff, matches the metrics comparison's unchanged `pytest_failed: 1`.

## Decisions

Unchanged from the prior attempt — still open, still genuinely the owner's call, carried forward verbatim:

```markdown
## Decisions
<!-- marvin:decisions -->
### quarantine-counts-as-produced: Does a quarantined (but not failed) digest count as "the Mini produced it"?
- [ ] A: Quarantined counts as produced — the Mini did its job; a held-back item is a safety-check outcome, not an outage. The laptop never rebuilds just because content got quarantined.
- [ ] B: Quarantined counts as not produced — if the brief chain got nothing usable, the laptop should still try, in case its own run clears the safety check.

### retire-cross-machine-merge: Remove `cross_machine_merge.py`'s LLM digest/research-digest merge step (`run_merge_authority`, `skills/improve/scripts/cross_machine_merge.py:350`) now, or leave it in place?
- [ ] A: Remove it now — ADR 0067 says this becomes unnecessary for these jobs, and it already runs zero LLM calls on a normal day (both its exists-checks fail), so there's nothing to lose by cutting the dead path.
- [ ] B: Leave it in place and remove it in a separate follow-up ticket.
```
Implementation defaults, unchanged: option A for `quarantine-counts-as-produced` (already how `lib/brief_fallback.py:105-107`/`:123-124` behave), option B for `retire-cross-machine-merge` unless Gil picks otherwise.

**Carried-forward notes, still true, still out of scope for this revision** (same reasoning as last time: none are in the must-fix list, and reopening them risks another unrelated denial on an already-twice-bounced ticket): `_infer_remote_path`'s outside-home fallback to `$HOME/.claude/<name>` (`lib/brief_fallback.py:43`); `run_colony.py:23`'s hardcoded `research-digest` path instead of reusing `research_digest.DIGEST_DIR`; `morning_brief.py`'s unused `write()` duplicating `build()`.

## Tests to write first

Mapped against the ticket's own "How we'll try to break it" list, plus the must-fix regressions:

1. **Mini down all morning → MacBook builds once, logs why** — already covered by `test_should_run_fallback_after_deadline_missing_remote` (`test_brief_fallback.py`) and `test_main_toctou_recheck_before_write` (`test_daily_digest.py`); for morning_brief, this is exactly `test_build_idempotency_with_fallback_gate`, which I'm fixing (below) rather than duplicating.
2. **Mini late but finishes after MacBook started → no double brief** — same TOCTOU tests as (1); `test_build_idempotency_with_fallback_gate`'s rewrite is the morning_brief instance of this case.
3. **Mini's output exists but is a failure placeholder → counts as not produced** — already covered, `test_produced_rejects_failure_placeholders`.
4. **Clock skew / MacBook asleep through deadline, builds once on wake** — already covered: `past_deadline()`/`produced()` are pure functions of wall-clock + file state (no session/elapsed-time state to desync), and the TOCTOU tests in (1)/(2) prove "wakes and finds it already built → builds nothing."
5. **Both Macs run the fallback check at the same moment** — already covered by the TOCTOU recheck tests in (1); both machines calling `should_run()` independently is exactly what `test_should_run_primary` / `test_should_run_fallback_after_deadline_missing_remote` prove deterministic.
6. **Real job output files in a temp HOME, never real `~/.claude`** — this is the must-fix list itself: items (7)-(10) below close the exact cases where this guarantee was broken.

Regression tests for the must-fix findings (each fails on current `HEAD`, passes after its fix):

7. **Rewrite `test_build_idempotency_with_fallback_gate`** (`lib/tests/test_morning_brief.py`) — reuse `test_daily_digest.py`'s stub shape: monkeypatch `brief_fallback.produced` to a fake that checks only the real local `path.exists()`/content (never remote), e.g. `lambda path, *a, **k: path.exists() and bool(path.read_text().strip())`. First `build()` call: file doesn't exist yet → proceeds to write; second call: file now exists for real → short-circuits. Proves idempotency without ever calling `read_remote`. Add an assertion that the stub's local-only logic path is what both the pre-check and TOCTOU recheck take (i.e. still exercises the real `build()` control flow, just with the SSH-touching tail cut off).
8. **New `utc_tz` fixture in `lib/tests/conftest.py`** — saves/restores the real `TZ` env var itself (not relying on `monkeypatch`'s teardown ordering, since `time.tzset()` must run *after* `TZ` is put back, and `monkeypatch`'s finalizer runs after any code in the requesting test/fixture body):
   ```python
   @pytest.fixture
   def utc_tz():
       import os, time
       old = os.environ.get("TZ")
       os.environimport
   ```
   (written out properly at implementation time as: set `TZ=UTC` + `tzset()`, `yield`, restore old value or `pop`, `tzset()` again in a `finally`). Apply it to all four `check_brief_builder` tests (`test_health_checks.py:1291-1374`) in place of their ad hoc `monkeypatch.setenv`/`tzset()` calls — closes the must-fix leak, and add one new assertion-level regression: **`test_check_brief_builder_does_not_leak_tz_to_later_tests`**, which runs a `check_brief_builder` test via the fixture, then — in the same test function, after that fixture's teardown would have run in a real suite — asserts `time.strftime("%Z")` is back to the pre-test zone (approximated with a nested `pytest.importorskip`-free manual fixture call, verifying the finalizer logic itself rather than relying on order-of-later-tests, which is non-deterministic to test directly).
9. **Rewrite `test_past_deadline_before`** (`lib/tests/test_brief_fallback.py:69-82`) — drop the unused `pytz` import and the always-true `hasattr` guard; use the new `utc_tz` fixture; assert directly: `now = datetime(2026, 10, 24, 8, 15, tzinfo=timezone.utc)` (already UTC-aware — no `.astimezone()` round-trip needed once `TZ=UTC` is pinned), `bf.past_deadline(now, usual_hour=8, usual_minute=30, grace_minutes=60) is False`.
10. **Rewrite `test_should_run_standby_before_deadline`** (`lib/tests/test_brief_fallback.py:110-124`) — add the `utc_tz` fixture so `now=08:00 UTC` is deterministically before `08:30` local on every host; additionally pass `run=MagicMock()` so even if the deadline math is later changed to cross the boundary, the test fails on a wrong assertion rather than silently hitting the network (belt-and-suspenders per `feedback-robust-durable-code`).
11. **`test_should_run_primary`** — add the `utc_tz` fixture for consistency with the rest of the file (no real bug here since `device_id` is explicit and `is_primary()` is pure, but keeping the whole file on one deterministic-clock convention avoids the next person reading it assuming otherwise).
12. **Extend the same `utc_tz` fixture to `test_builder_of_default_day_uses_injected_now_not_wall_clock` and `test_builder_of_default_matches_build_local_date`** (`lib/tests/test_morning_brief.py:197-231`) — these assert `mb._day(injected_now) == "2026-10-24"` / compare against a UTC-constructed `fixed_now`, which is only guaranteed on hosts where local time doesn't cross a calendar day relative to UTC (true for Gil's US zones, false in principle on e.g. UTC-10 or UTC+13). Same bug class as (2)/(10), same fixture fixes it; this is new ground beyond the literal must-fix list but is the same root cause already proven live in this file, so it's cheap and in scope to close now rather than leave for a third round.

Run scoped to touched functions only: `lib/tests/test_health_checks.py -k "brief_builder"`, `lib/tests/test_morning_brief.py -k "idempotency or builder_of"`, `lib/tests/test_brief_fallback.py -k "past_deadline or should_run"` — confirm each fails against current `HEAD` (where applicable — (8)/(9)/(10)/(12) are currently *passing by accident*, not failing, so "fails first" means demonstrating the TZ-dependency/leak directly, e.g. by asserting `time.tzname` is restored, or by temporarily forcing a non-UTC `TZ` before the fix and showing the old assertions break) and pass after. Then the full `lib/tests/` + `skills/improve/scripts/tests/` + `skills/research-colony/scripts/tests/` suites, confirming `test_no_hardcoded_home.py`'s pre-existing failure is the only one left.

## Task List

1. Add `utc_tz` fixture to `lib/tests/conftest.py`: saves/restores the real `TZ` env var manually (not via `monkeypatch`, so the ordering of the `tzset()` restore is correct), setting `TZ=UTC` + `time.tzset()` on entry and restoring + re-`tzset()` in a `finally` on exit.
2. Edit `lib/tests/test_health_checks.py`: replace the four tests' inline `monkeypatch.setenv("TZ", "UTC"); time.tzset()` with the `utc_tz` fixture parameter; add `test_check_brief_builder_does_not_leak_tz_to_later_tests`.
3. Edit `lib/tests/test_brief_fallback.py`: rewrite `test_past_deadline_before` (drop `pytz` import and the always-true guard, use `utc_tz`); add `utc_tz` to `test_should_run_standby_before_deadline` (plus `run=MagicMock()`) and to `test_should_run_primary`.
4. Edit `lib/tests/test_morning_brief.py`: rewrite `test_build_idempotency_with_fallback_gate` to stub `brief_fallback.produced` with a local-only fake (per test 7 above) instead of leaving it real; add `utc_tz` to `test_builder_of_default_day_uses_injected_now_not_wall_clock` and `test_builder_of_default_matches_build_local_date`.
5. Run the scoped test selections from "Tests to write first," confirming each new/rewritten assertion actually exercises the bug it claims to catch (temporarily reverting a fix locally to see the test fail, then reapplying).
6. Run the full `lib/tests/`, `skills/improve/scripts/tests/`, `skills/research-colony/scripts/tests/` suites; confirm only the pre-existing, unrelated `test_no_hardcoded_home.py` failure remains.
7. Leave the Decisions block and the three carried-forward notes unchanged in the PR description; flag the pre-existing `test_no_hardcoded_home.py` failure again as a separate, out-of-scope blocker for the merge gate.