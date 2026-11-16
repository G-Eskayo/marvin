## North-star fit

**Reuses:** `skills/improve/scripts/cross_machine_merge.py:68` already has the exact correct line — `TODAY = date.today().isoformat()` — this fix makes `daily_digest.py:40` match it verbatim. No new abstraction, no new file: a one-line change plus a module-level `import date`. Tests reuse the existing monkeypatch/`tmp_path` conventions and the autouse `_pinned_machine_role` fixture already in `skills/improve/scripts/tests/test_daily_digest.py`.

**Simplicity:** the simplest sufficient fix — change one assignment to match the already-correct pattern used by every reader (`cross_machine_merge.py`, `session_start_report._check_digest` via `.astimezone()`, `research_digest.py`). No migration, no new dependency (confirmed `freezegun` isn't installed or used anywhere in this repo — tests simulate timezones with `os.environ["TZ"]` + `time.tzset()`, which is the only mechanism available and is POSIX-only, matching the `linux-ok`/macOS-only scope implied by the ticket's labels).

**Tokens:** spends ~0 extra tokens at runtime (no model call changes); the only cost is a slightly longer test file, run locally/in CI, not against a model.

**Capability:** fixes a silent, latent failure (missing session-start digest line, stale digest) that previously took Gil noticing an absence to catch — this makes every machine agree on "today" regardless of time zone, satisfying north star 5 directly.

**Scope note:** the ticket's "What to build" and "Acceptance criteria" sections are fully covered below. Its separate "Recurrence check" section asks for a *new* probe ("add one... from the session-start log") — but no code today logs `check_daily_digest()`'s daily outcome anywhere durable (`FULL_REPORT` is overwritten each session, not appended), so building that probe means adding new logging infrastructure, which is real scope beyond a one-line, low-effort fix. `fit_check.py:40` confirms a missing/malformed Recurrence check is a **warning, not a merge block** (`outcome_check_block` is parked in `config/parked.json`), so this doesn't block verification. I'm flagging it as a Decision rather than quietly building new logging or quietly skipping the ticket's explicit ask — see Decisions below.

## Tests first

All in `skills/improve/scripts/tests/test_daily_digest.py`, using a new helper fixture that: sets `TZ` via `monkeypatch.setenv`/`delenv`, calls `time.tzset()`, monkeypatches `time.time` to a fixed epoch, then `importlib.reload(dd)` so the module-level `TODAY`/`OUT_FILE` recompute under the simulated instant — and in a `finally`, restores `TZ` via another `tzset()` call and reloads `dd` again so no global state leaks into other tests (this exact leak risk — a module-level constant computed at import time — is the most likely thing a naive version of this test gets wrong).

1. **AC1 (exact scenario):** clock frozen at 2026-11-12 23:30 local in UTC-8 (= 2026-11-13 07:30 UTC) → `dd.OUT_FILE.name == "2026-11-12.md"`.
2. **AC2 (writer/reader agreement, both directions):** parametrized over a zone west of UTC (`Etc/GMT+8`) and a zone east of UTC (`Etc/GMT-9`), for the same frozen instant — assert `dd.TODAY` equals the date `session_start_report._check_digest`'s logic would compute for that same frozen instant (reuse `_now().astimezone().strftime("%Y-%m-%d")` computed against the same monkeypatched `time.time`).
3. **AC3 (temp HOME):** already satisfied by existing `tmp_path`/`monkeypatch.setattr(dd, "DIGEST_DIR"/"OUT_FILE", ...)` conventions — verify no test in the new set touches the real `~/.claude`.
4. **Break-it: midnight boundary x2 zones:** parametrized `(23:59, 00:01) x (UTC-8, UTC+9)` — four cases, each asserting writer/reader date agreement (same mechanism as #2, tighter instants).
5. **Break-it: stale old-UTC-named file present:** create a leftover file named under the *old* (UTC) convention in `DIGEST_DIR` (a different name than today's local-dated `OUT_FILE`), run `dd.main()` with `call_claude` mocked to return content and the gate pinned to primary — assert no exception is raised and the new local-dated `OUT_FILE` is written with fresh content (the leftover file is simply ignored, since `produced()` only ever checks the exact path it's given).
6. **Break-it: TZ unset:** `monkeypatch.delenv("TZ", raising=False)` + `tzset()`, reload — assert `dd.TODAY` still equals `_check_digest`'s computed date for the same instant (both fall back to the system zone identically, since neither reads `TZ` directly).
7. **Regression guard:** `dd.TODAY` is produced by `date.today()`, not `datetime.now(timezone.utc)` — a simple `inspect`/source-level or behavioral assertion (covered implicitly by #1 already distinguishing the two: at that frozen instant the UTC date and local date differ, so a passing #1 is itself the regression guard).
8. **Existing suite stays green:** no changes to `bench_summary`, `reviewer_health_summary`, TOCTOU, or gate tests — confirms the one-line change doesn't ripple.

## Decisions
<!-- marvin:decisions -->
### probe: Build the Recurrence-check probe now, or defer it?
- [ ] A: Defer — ship the one-line fix + tests now; open a separate follow-up ticket for the probe (it needs new logging in `session_start_report.py` that doesn't exist yet: appending each `check_daily_digest()` outcome to a durable per-day log, since `FULL_REPORT` is overwritten every session)
- [ ] B: Build it now in this PR — add the logging plus a `_digest_date_mismatch_days`-style probe in `lib/purpose_metrics.py`'s `PROBES` dict (pattern: `_missing_model_failures`), and update the issue's `Recurrence check` → `Probe:` field to the registered name

## Task List

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