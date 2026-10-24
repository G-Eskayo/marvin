All three fallback plists and all the primary-side changes check out. I now have complete, verified ground truth. Writing the revised plan.

## North-star fit

**Reuses before adding anything new:** every production primitive the ticket needs is already written and wired in this worktree — `brief_fallback.should_run()`/`produced()`/`record_built_by()` (`lib/brief_fallback.py`), consumed identically by all three producers: `skills/improve/scripts/daily_digest.py:main()` (lines 274-345, with its own `OUT_FILE.exists()` dedupe and a TOCTOU recheck), `skills/research-colony/scripts/research_digest.py:generate()` (lines 100-174), `skills/research-colony/scripts/run_colony.py:main()` (lines 21-46), and `lib/morning_brief.py:build_cli()` (lines 312-326, already extracted from `__main__` and tested). `health_checks.check_brief_built_by()` (lines 411-434) reuses `_result()`'s green/yellow/red shape, matching `check_catalog_fresh()`. `cron_health.JOBS` and `health_checks.JOB_PLACEMENT` already carry the four new mini/laptop entries, and all three fallback plists exist with correct schedules. I am adding nothing here — I verified every one of these by reading the live file, not by trusting the prior design doc's text.

**This design doc corrects the prior one rather than repeating it.** I re-verified every defect the prior attempt claimed and most of them are not real against the code actually on disk:

- Claimed defect "research_digest.generate() has no out_path.exists() guard" — **false**, it's at lines 113-115, already there.
- Claimed defect "run_colony.py double-calls record_built_by()" — **false**, `run_colony.py:main()` never calls `record_built_by` at all; only `generate()` does, on its own successful-write path.
- Claimed defect "morning_brief.py's CLI logic is untestable, stuck in `__main__`" — **false**, it's already extracted into `build_cli()` and `lib/tests/test_morning_brief.py::test_build_cli_skips_when_should_run_returns_false`/`test_build_cli_builds_and_records` already exist and pass.
- Claimed defect "`past_deadline`/`should_run` compute the deadline in UTC instead of local wall-clock" — this one **was real** and is **already fixed**: both `lib/brief_fallback.py:139` and `:205` already call `.astimezone()` before `.replace(hour=..., minute=...)`.
- The prior plan's task list even named a file that doesn't exist (`lib/tests/test_cron_health.py` — cron-health coverage lives inside `lib/tests/test_health_checks.py` per ADR 0033, there's no standalone file). That plan was reasoning about a stale or imagined snapshot of this branch, not the code actually here.

**The one real, still-open defect, found by running the suite, not by reading claims:** the `.astimezone()` fix landed correctly in the code, but two *pre-existing* tests in `lib/tests/test_brief_fallback.py` were never updated to match, and now encode the old, wrong assumption that `usual_hour`/`usual_minute` live in the same timezone as `now` (both tests build a fixed UTC `now` and expect the deadline math to stay in UTC). On this host (`TZ=America/Denver`), that assumption is now false, and I confirmed both fail when run in isolation:

```
FAILED lib/tests/test_brief_fallback.py::test_past_deadline_true_when_past
FAILED lib/tests/test_brief_fallback.py::test_should_run_on_fallback_skips_if_fresh
2 failed, 17 passed in 7.82s
```

This exactly accounts for the reported regression (`pytest_failed` baseline 1 → current 3): the baseline 1 is `lib/tests/test_no_hardcoded_home.py::test_no_code_hard_codes_the_mac_home_directory`, a pre-existing, unrelated failure (`docs/screenshots/vitals-v4/data.js` hardcodes `/Users/gileskayo`, not in this ticket's scope — confirmed it fails the same way with zero files from this ticket touched). The other two are exactly the ones above. **The regression is caused by a correct code fix landing without its matching test update — not by broken production code.**

Two more things I found while verifying, both quality gaps rather than correctness bugs:

- `test_past_deadline_uses_astimezone` and `test_should_run_fresh_after_uses_local_time` (the prior attempt's own regression tests for this exact bug) only assert `isinstance(result, bool)` or rely on a huge `grace_minutes=3600` — they would pass even if `.astimezone()` were deleted entirely. They don't actually pin the behavior they claim to guard.
- `test_past_deadline_false_before_grace` currently passes only by coincidence of this host's UTC offset (both the expected and actual deadlines land on the same side of `now` regardless of the TZ shift) — it would silently start failing on a host in a different timezone. Same underlying lesson: a test fixture that hardcodes "now is UTC, usual_hour is UTC" is accidentally timezone-dependent on *grading*, not just on behavior.

**Simplest sufficient approach:** fix the tests, not the code — the code's `.astimezone()` behavior is the correct semantic (launchd's `StartCalendarInterval` fires on local wall-clock time, so `usual_hour`/`usual_minute` must be interpreted as local, and `now` — always UTC in production via `datetime.now(timezone.utc)`) must be converted to local before comparing). Rewriting three tests plus strengthening two weak ones is the whole fix. No production file changes are needed for the four acceptance criteria — they're already met and tested, verified by running `lib/tests/test_health_checks.py` (137 passed alone) and `skills/research-colony/scripts/tests/` + `skills/improve/scripts/tests/test_daily_digest.py` (28 passed alone).

**Where this saves tokens:** doing nothing beyond the test fix avoids re-touching five already-correct production files for no reason — the previous attempt's 11-item task list would have spent tokens "fixing" things that work, which is exactly what north star 1 argues against. The actual ADR 0067 token-halving (one model call instead of two for digest/colony/brief) is already in effect in this diff; this plan's only job is to make the test suite agree with it.

**More capable or more passive:** more capable — once the two tests are corrected, the suite accurately reflects reality (a rerun on the Mini, a launchd catch-up after sleep, or a manual retry won't burn a second model call or create a sync conflict), and nobody is misled by a green-looking PR that's actually hiding a real timezone bug behind weak assertions.

**One thing to flag, not fix:** `skills/improve/scripts/daily_digest.py:285-287`'s `OUT_FILE.exists(): return` guard treats its own failure-placeholder file (written even when `call_claude()` fails, per lines 341-344, specifically so the failure is visible on disk) as "already done" on a same-day local retry, since that guard checks file existence, not the sidecar. This predates #458 (it's the TOCTOU dedupe pattern, not the primary/fallback feature) and only affects intra-machine retries, not the Mini-vs-laptop fallback this ticket is about — `produced()`/`should_run()` correctly check the *sidecar*, not `OUT_FILE.exists()`, so a failure placeholder correctly does **not** count as produced across machines (the exact "failure placeholder" bullet in the ticket's break-it list is already satisfied). I'm not touching this; flagging it so it isn't lost.

## Decisions

Unchanged, carried forward from `docs/design/pipeline-g-eskayo-marvin-458.md` and already reflected in `CONTEXT.md`'s "Cross-machine merge idle path" note — still genuinely open, still not required for the four acceptance criteria:

```markdown
## Decisions
<!-- marvin:decisions -->
### retire-cross-machine-merge: Retire cross_machine_merge.py's LLM-merge-digest path now?
Once the Mini is the sole producer of daily-digest/research-digest on a normal day, `cross_machine_merge.py`'s *second* job — reconciling two divergent LLM write-ups — has nothing left to reconcile (its *first* job, syncing research-feed/qa-knowledge items, stays useful and is untouched either way). It still runs daily via `check_and_trigger_merge.py`.
- [ ] A: File a follow-up ticket now to retire just the LLM-merge-digest half of `cross_machine_merge.py` (keep the item-sync half)
- [ ] B: Leave it as dead-weight-but-harmless for now; revisit only if it causes a problem
```

## Tests to write first

All in `lib/tests/test_brief_fallback.py`, the only file this plan touches. Each is written to fail against the current file (proving it actually catches the TZ assumption) before the rewrite, and pass after:

1. **Rewrite `test_past_deadline_true_when_past`** — instead of a bare `NOW.replace(hour=9, minute=40)` compared against a hardcoded "8:30 UTC + 60min" expectation, derive the local deadline the same way the code does (`now.astimezone().replace(hour=8, minute=30, ...)`), add `grace_minutes` plus 10 minutes, convert back to UTC, and assert `past_deadline(...)` is `True` for an instant just after that boundary. This makes the test pass under *any* host timezone, not just the one it happened to be authored on. This is the regression test for the real bug: it must fail against today's already-correct code only if the *test* still hardcodes the old UTC-literal assumption — i.e. this change fixes the test, verified by reverting `.astimezone()` in `past_deadline()` and confirming the rewritten test then fails.
2. **Rewrite `test_past_deadline_false_before_grace`** the same way, asserting `False` for an instant 10 minutes *before* the derived boundary — removes the "passes by coincidence of this host's offset" landmine.
3. **Rewrite `test_should_run_on_fallback_skips_if_fresh`** — keep the existing primary/fallback registry mocking, but set the sidecar's `built_at` to "now" (real `datetime.now(timezone.utc)`, like the already-added `test_should_run_fresh_after_uses_local_time` does) rather than a fixed calendar date compared against a small, timezone-sensitive grace window. Assert `should_build is False` and `"fresh"` in the reason, with a `grace_minutes` small enough (e.g. 60) that the assertion is still meaningful rather than vacuous.
4. **Strengthen `test_past_deadline_uses_astimezone`** — replace the `isinstance(result, bool)` assertions with the same derive-and-compare pattern as test 1, so flipping `.astimezone()` back to plain `now.replace(...)` actually breaks this test. Consider folding it into the rewritten test 1 rather than keeping both (duplication of the same assertion under two names adds nothing — composability/KISS; two near-identical tests for the same boundary is one test too many).
5. **Strengthen `test_should_run_fresh_after_uses_local_time`** — it currently only proves "a brief built *just now* is fresh," which is true independent of the timezone fix. Add a second assertion in the same test (or a sibling test) for a brief built local-*yesterday*-equivalent-but-UTC-today (a date right at the local midnight boundary) to actually exercise the local-vs-UTC day/hour divergence, not just "recent is fresh."
6. Run the full file afterward and confirm `17 → N` tests, all green, with no change to `lib/brief_fallback.py` itself — proving the bug was in the tests, not the production code.

No other test files need new cases: `check_brief_built_by()` (AC4), `JOB_PLACEMENT`/`cron_health.JOBS` (AC1), and the dedupe/TOCTOU/failure-placeholder/SSH-failure/clock-skew/concurrent-fallback scenarios from "How we'll try to break it" are already covered by the 137 passing `test_health_checks.py` cases, the 28 passing research-colony/daily-digest cases, and the 17 (soon ~16, after folding #4 into #1) other `test_brief_fallback.py` cases I re-ran and read individually. "Both Macs run the fallback check at the same moment" needs no new test: `scanner_role.is_primary(device_id)` is a pure function of a static device id, not of wall-clock time, so simultaneity on two machines can't change which one `should_run()` tells to build — the Mini always builds, the laptop's decision depends only on what it can read from the Mini's sidecar at that instant, a case already covered by the existing stale/fresh/SSH-failure tests.

## Task List

1. In `lib/tests/test_brief_fallback.py`: rewrite `test_past_deadline_true_when_past` and `test_past_deadline_false_before_grace` to derive the expected local deadline via `.astimezone()` instead of assuming `now`'s UTC hour equals the local schedule hour (tests 1-2 above).
2. In `lib/tests/test_brief_fallback.py`: rewrite `test_should_run_on_fallback_skips_if_fresh` to build its sidecar against real "now" rather than a fixed calendar fixture (test 3 above).
3. In `lib/tests/test_brief_fallback.py`: fold `test_past_deadline_uses_astimezone`'s assertions into the rewritten test 1 and delete the now-duplicate test function; strengthen `test_should_run_fresh_after_uses_local_time` with the local-day-boundary case (tests 4-5 above).
4. Run `lib/tests/test_brief_fallback.py` alone before and after each rewrite, confirming each rewritten test fails against the pre-rewrite version for the stated reason and passes after.
5. Run `lib/tests/test_health_checks.py`, `skills/research-colony/scripts/tests/`, `skills/improve/scripts/tests/test_daily_digest.py`, and `lib/tests/test_morning_brief.py` once more, each in isolation, to confirm no change to production code was needed and nothing else regressed.
6. In the PR description: state plainly that AC1/AC3/AC4 were already implemented and tested by the prior attempt and this PR's only change is the two test rewrites; name the pre-existing, out-of-scope `test_no_hardcoded_home.py` baseline failure so the reviewer doesn't attribute it to this diff; restate (carried from the prior attempt) that `cross_machine_merge.py` is untouched pending the `retire-cross-machine-merge` Decision, and that installing the new/changed plists via `launchctl bootstrap`/`bootout` on the physical Macs is a manual step outside this diff's reach — AC1 is code-ready, not yet in effect on either machine until that step happens.