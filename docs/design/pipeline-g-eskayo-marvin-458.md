Write access is restricted here (same as the prior attempt), so I'm giving you the design doc as text instead of a file — it is plan-only work regardless.

## North-star fit

**Reuses before adding anything new.** This worktree already carries almost all of this ticket's substance from earlier attempts (uncommitted — `git diff --stat` shows 13 files touched). Verified against the live files, not the old doc's claims:

- `lib/brief_fallback.py` — `Decision` (with `role`), `_home_relative_cat`, `read_remote`, `produced`, `past_deadline` (with `tz`), `should_run` (wrapped in one `try/except`, `run=` forwarded) all exist and match CONTEXT.md's "Brief owner" bullet (`CONTEXT.md:1466-1472`) and ADR 0067.
- `lib/health_checks.py::JOB_PLACEMENT` and `check_brief_builder` (line 447) — AC1's placement table and AC4's "which machine built it" surface are both live.
- `lib/cron_health.py::JOBS` and all six launchd plists exist with the documented HH:MM schedule.
- `morning_brief.py::build()` already threads `decision.role` into `builder_reason` (line 310) — the role-mislabeling bug from the *previous* review round is fixed and stays fixed; not touched again.
- `daily_digest.py` (lines 276-283, 328-331) already has the pattern needed for fix 2: gate on `should_run()`, re-check `brief_fallback.produced(OUT_FILE)` — not `path.exists()` — both before doing the work and again right before writing, to close the two-writers race. **This is the exact pattern `morning_brief.write()` is missing and will reuse**, from `skills/improve/scripts/daily_digest.py::main()`.

None of the above is redone here — redoing correct code is waste against north star 1.

**What's still broken**, confirmed by reading the live files against the latest review:

1. `lib/brief_fallback.py:100` (`past_deadline`) and the call in `should_run` (line 143) — the standby's deadline is the *primary's own scheduled time* (`usual_hour`/`usual_minute`, e.g. 8:30 for daily-digest), with no grace window, strict `>`. A MacBook's gate opens at 08:30:01 — one second after the primary's own schedule — not an hour later. This contradicts the ticket text ("one hour after the usual time"), CONTEXT.md's "Brief owner" bullet ("+60 minutes"), every plist, and `cron_health.py::JOBS`. Only `brief_fallback.py`'s own module docstring (line 6: "30 minutes later") disagrees with all four — that's just a wrong line, fixed here, not a second source of truth.
2. `lib/morning_brief.py:287` (`write()`) — early-returns on `path.exists()`, not `brief_fallback.produced(path)`. A brief that's empty or contains the `"(claude call failed:"` placeholder gets treated as done and never repaired for the rest of the day. This is also the only place in the pipeline that doesn't use the `produced()` gate everything else already uses.

**Simplest sufficient approach:** two small additive signature changes plus reusing an existing pattern once — no new files:

- `past_deadline(hour, minute, now=None, tz=None, grace_minutes: int = 0)` — add `grace_minutes`, applied via `deadline + timedelta(minutes=grace_minutes)` (timedelta handles rollover correctly; no hand-rolled hour overflow math). Default `0` keeps every existing caller/test byte-for-byte unaffected.
- `should_run(..., grace_minutes: int = 60)` — thread into the one `past_deadline()` call and into the reason string. `60` isn't a guess: it's already in the ticket text, CONTEXT.md, every plist, and `cron_health.py`. No caller needs to change.
- `morning_brief.py::write()` — swap `path.exists()` for `brief_fallback.produced(path)` at the top gate, and add the same second `produced()` re-check `daily_digest.py` already has, right before `path.write_text(...)`, closing the "both Macs decide to build at the same instant" race the ticket lists — today `write()` has no re-check at all between `gather()` and writing.

**Tokens:** zero new LLM calls, zero new files, two signature-additive changes plus one re-check line reused verbatim from a pattern one directory over.

**More capable, not more passive:** closes the gap that would let a stale MacBook plist double-build every morning (defeating the ticket's whole point), and the gap that leaves a failed brief silently stuck all day with no path to repair.

## Decisions

None. Both fixes are fully determined by already-recorded decisions: the one-hour grace window is in the ticket text, CONTEXT.md, every plist, and `cron_health.py::JOBS` (all agree); `produced()` as the sole definition of "already built" is in CONTEXT.md's same bullet and already how every other call site behaves. The prior attempt's `retire-cross-machine-merge` decision concerns `cross_machine_merge.py`, untouched either way — carries forward into the PR body unchanged.

## Tests to write first

Against real `scanner_role`/`machine_profile`/`task_dispatch` objects, as the existing suite already does; only the SSH process boundary (`run=`) is faked.

**Regression tests, one per must-fix finding (verified failing today):**
1. `test_should_run_grace_window_has_not_passed_right_after_usual_time` — standby, `now` = usual time + 1s, default `grace_minutes=60` → `Decision(False, ...)`. The exact stale-plist scenario from the review. **Fails today.**
2. `test_should_run_grace_window_passes_after_an_hour` — `now` = usual time + 61min → `Decision(True, ...)`. Guards against overcorrecting into "never opens."
3. `test_past_deadline_grace_minutes_is_additive` — direct unit test on `past_deadline` with `grace_minutes=60`.
4. `test_past_deadline_default_grace_minutes_is_zero_unchanged` — existing test_6/7/8/9 bodies verbatim, no `grace_minutes` arg — proves additive, not a behavior change.
5. `test_write_repairs_a_stale_failure_placeholder_brief` — pre-write today's `.md` with the placeholder; `mb.write()` must produce fresh content. **Fails today.**
6. `test_write_repairs_an_empty_brief_file` — same shape, empty file.
7. `test_write_does_not_rewrite_a_valid_existing_brief` — pre-write valid sentinel content; must stay untouched (guards AC2).
8. `test_write_does_not_clobber_a_file_that_appears_mid_gather` — monkeypatch `gather` to write a competing valid file as a side effect (simulating the other machine finishing first); the pre-write re-check must keep that file, not overwrite it. **Fails today** (no re-check exists between `gather()` and the write).

**Ticket's "How we'll try to break it" (already covered, re-verified, no new test needed):** Mini-down-all-morning (`test_17/19` + `test_build_calls_write_with_fallback_reason_when_should_run`); failure-placeholder-counts-as-not-produced (`test_13` + new 5/6); clock skew/sleep (should_run is a pure function of `now`, exercised by test 2); same-instant race (new test 8); temp-HOME discipline (already universal in the suite).

**Misuse bar beyond the ticket's list (already covered, re-verified, no gaps):** unreadable file (`test_14`), SSH timeout (`test_19`'s offline path), registry/`is_primary`/`_primary_device` raising (`test_20`'s catch-all).

**Verify fails when code changes without a test changing:** run `lib/tests/test_brief_fallback.py`, `lib/tests/test_morning_brief.py`, `lib/tests/test_health_checks.py -k "brief_builder or job_placement"`, `skills/improve/scripts/tests/test_daily_digest.py`, `skills/research-colony/scripts/tests/test_run_colony.py`. Tests 1, 2, 3, 5, 6, 8 must fail before the fix and pass after; 4 and 7 must pass unchanged both before and after; every other existing test unaffected.

## Task List

1. `lib/brief_fallback.py::past_deadline`: add `grace_minutes: int = 0`; apply via `deadline + timedelta(minutes=grace_minutes)`. Fix the module docstring's "30 minutes later" → "an hour later (09:30, 10:00, 10:45)".
2. `lib/brief_fallback.py::should_run`: add `grace_minutes: int = 60`, forward to `past_deadline(...)`, include in the "deadline has not yet passed" reason string. Update docstring.
3. `lib/tests/test_brief_fallback.py`: add tests 1-4 above.
4. `lib/morning_brief.py::write()`: replace `path.exists()` with `brief_fallback.produced(path)` at the top gate; add a second `produced()` re-check immediately before `path.write_text(...)` — if true, return the existing path without writing.
5. `lib/tests/test_morning_brief.py`: add tests 5-8 above.
6. Run the five targeted suites; confirm the fail-before/pass-after split matches exactly.
7. PR description: carry forward the `retire-cross-machine-merge` decision unchanged; note that installing the six plists via `launchctl bootstrap` on the physical Mini/MacBook is a manual step this diff cannot perform.