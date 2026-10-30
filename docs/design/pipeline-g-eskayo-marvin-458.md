## North-star fit

**Reuses:** `lib/scanner_role.py`'s `is_primary()` / `PRIMARY_PREFIX` (primary/standby pattern already built for the ticket scanner, ADR 0032) — the new `lib/brief_fallback.py` module is explicitly the same shape applied to dated output files instead of heartbeats, so it imports `is_primary` from `scanner_role.py` rather than reimplementing machine-primacy logic. It also reuses `lib/machine_profile.py`'s `remote_devices()`/`registry_id()`/`machine_label()` (device registry, already used by `cross_machine_merge.py` and `scanner_role.py`) and `lib/task_dispatch.SSH_OPTS` (same SSH option set used everywhere else cross-machine). No new cross-machine primitive is invented.

**Simplest sufficient approach:** one small gate module (`should_run()`/`produced()`) that each of the three jobs calls at the top of its own `main()`/`generate()`, plus a thin `.built-by` sidecar on the brief for the "which machine built it" acceptance criterion. No new daemon, no new state machine, no scheduler — launchd's existing per-job plists just get a second ("-fallback") copy with a later time, matching the primary/standby pattern already used for the ticket scanner. The fan-out-and-merge machinery (`cross_machine_merge.py`) is left untouched: on a normal day the laptop never builds its own copy, so `run_merge_authority()`'s existing `if not local_file.exists(): skip` already turns the merge into a no-op — nothing to add there.

**Token/cost:** removes a full daily LLM call on the MacBook for both the daily digest and the research colony (today both machines call Claude independently) — this is the whole point of ADR 0067, directly serving north star 1. The brief itself already costs zero model calls (`lib/morning_brief.py`'s docstring) and stays that way.

**Capability:** this is pure infrastructure — it makes an existing daily output more reliable (one trustworthy build instead of two diverging ones) without changing what Gil sees, except that Health now names which machine built today's brief. Not user-facing capability growth; it removes waste and a recurring sync-conflict failure mode, which is the correct call here — a north star doesn't argue against this.

**Existing state found:** PR **#600** (branch `pipeline/g-eskayo/marvin#458`) already implemented this design once and reached "Verification passed" twice, but was denied on dashboard review for `GATE_TESTS_FAILED` and then hit an unresolvable rebase conflict and went stale. I read that PR's full diff. The design was sound; the two concrete defects that sank it were:
1. `lib/tests/test_no_hardcoded_home.py::test_no_code_hard_codes_the_mac_home_directory` fails **on current `main` already**, unrelated to this ticket — a generated snapshot file `docs/screenshots/vitals-v4/data.js` contains a literal `/Users/gileskayo` path. This blocks the merge gate for *any* PR right now, not just this one.
2. The PR's `skills/improve/scripts/tests/test_daily_digest.py` was a wholesale replacement of a file that, on `main`, now independently holds ~30 unrelated tests (`bench_summary`, `reviewer_health_summary`, etc. — added after the PR's branch point). Rebasing produced the reported `SyntaxError: from __future__ imports must occur at the beginning of the file` — a bad auto-merge of two unrelated test files at the same path, not a logic bug. This attempt must **add** fallback-gate tests to the existing file, never replace it.

This plan reproduces #600's design on top of current `main`, fixes both defects, and closes one gap #600 left half-done (see Decisions below).

## Tests to write first

Mapped to the ticket's "How we'll try to break it" list, plus misuse categories the list didn't name:

**`lib/tests/test_brief_fallback.py`** (new file; `lib/tests/conftest.py` already puts `lib/` on `sys.path`, so no manual `sys.path.insert` needed, unlike #600's version):

- `test_mini_always_builds_without_checking_anything` — primary never touches `run`/SSH at all.
- `test_laptop_waits_before_the_deadline` — standby before deadline never calls `run` (asserts via a `run` that raises if invoked).
- `test_mini_down_all_morning_laptop_builds_once` — **ticket item 1**: first call (primary unreachable) → build; primary's local file then appears → second call → don't rebuild.
- `test_pre_write_recheck_catches_remote_only_produced_during_generation` — **ticket item 2**: decision is True, primary finishes mid-generation, a second `should_run()` call (the pre-write recheck) flips to False — proves one wins deterministically, not "whoever finishes writing first."
- `test_failure_placeholder_counts_as_not_produced` / `test_produced_returns_false_for_failure_marker` (substring, not just prefix) — **ticket item 3**.
- `test_produced_returns_true_for_quarantine_marker` — quarantine is an outcome, not an outage (distinguishes failure from a safety hold).
- `test_clock_skew_never_compares_across_machines` — **ticket item 4** (clock skew): asserts `past_deadline`'s signature carries no device/remote-clock parameter, i.e. the decision is provably a pure function of this machine's own wall clock.
- `test_laptop_wakes_late_and_builds_exactly_once` — **ticket item 4** (asleep through deadline): a laptop that calls `should_run()` for the first time at, say, 14:00 (having been asleep since before 08:30) gets `True` once; a second call afterward (file now exists) gets `False` — "wakes once, doesn't flap."
- `test_same_day_idempotent_across_repeated_calls` and `test_both_machines_decide_independently_from_same_state` — **ticket item 5**: both Macs evaluating `should_run()` at the same instant from the same observable state (same `now`, same `produced()` result) get the *same* answer without talking to each other — no coordination primitive needed because the function is pure and deterministic.
- `test_registry_lookup_failure_treated_as_not_produced` — a dependency (the machine registry file) failing is caught, not raised; fails open to "try to build."
- `test_unreadable_local_file_falls_through_to_remote` — wrong permissions on the local file; rewritten to call `produced()` directly with `try/finally` chmod restore and a root skip (per #600's denial-feedback fix notes — running as root bypasses the permission bit).
- `TestInferRemotePath`: `test_infer_remote_path_preserves_subdirectory` (parametrized over `daily-digest`, `research-digest`, `briefs` output dirs) and `test_infer_remote_path_falls_back_to_filename_outside_home` — a misconfigured path outside `$HOME` degrades gracefully instead of crashing.
- `TestReadRemote`: `test_read_remote_lets_home_expand_but_quotes_rest` and an adversarial `test_read_remote_resists_shell_injection` — constructs the actual remote command string `read_remote()` would send and **executes it through a real local `sh -c`** (not a mock) with a path containing `; touch`/backtick/`$()` payloads, then asserts no injected command actually ran. This is "test against the real collaborator" (the remote shell) applied locally, and the adversarial command-injection attack the north stars require for anything that builds a shell command from external-ish input (a remote path).
- All of `TestProduced` (missing file, empty, whitespace-only, remote-missing, remote-empty) — **ticket item 6**: every one of these runs against real files under `tmp_path`, never `~/.claude`.
- `TestPastDeadline`: before / at-exactly / within-grace / just-past-grace / much-later boundary tests.
- `test_should_run_with_custom_deadline_hour`, `test_past_deadline_with_custom_grace` — parameterization regression guards (each job uses a different deadline: digest 08:30, colony 09:00, brief 09:15).

**`skills/improve/scripts/tests/test_daily_digest.py`** (add to the existing ~30-test file, do not replace it):
- `test_gate_off_skips_without_writing` — `should_run()` False → `call_claude`/write never invoked.
- `test_gate_on_proceeds_to_build` — `should_run()` True (primary) → existing happy path unaffected (regression guard that the gate didn't break the primary builder).
- `test_toctou_recheck_skips_write_if_produced_during_generation` — `produced()` flips True between the initial gate and the final write; file is not overwritten.
- **Fix required to an existing test**: `test_main_short_circuits_when_out_file_exists` currently doesn't mock `should_run`/device identity. Once the gate sits at the top of `main()`, this test would start depending on the real machine's registry id and real wall clock (flaky, environment-dependent) instead of testing what it claims to test. It must be updated to monkeypatch `daily_digest.brief_fallback.should_run` to return `Decision(True, "primary")` so it isolates the short-circuit-on-existing-file behavior from gate behavior — exactly the kind of test-must-change-with-the-code case the merge gate checks for.

**`skills/research-colony/scripts/tests/test_run_colony.py`** and **`test_research_digest.py`** (new directory + files, following `skills/improve/scripts/tests/test_daily_digest.py`'s existing `sys.path.insert(str(Path(__file__).resolve().parents[1]))` pattern since there's no conftest here yet):
- `test_main_skips_source_monitor_when_gate_is_closed` — standby before deadline never calls `source_monitor.main()`/`correlate.correlate()` (checked via raise-on-call sentinels, same technique as the daily-digest test).
- `test_main_runs_normally_when_gate_is_open`.
- `test_generate_treats_failure_placeholder_as_not_produced` (swap of `out_path.exists()` → `brief_fallback.produced(out_path)`).
- `test_generate_toctou_recheck_skips_write`.

**`lib/tests/test_morning_brief.py`** (add to existing file):
- `test_write_is_idempotent_against_an_existing_file` — second `write()` for the same day doesn't overwrite.
- `test_write_records_who_built_it` — `.built-by` sidecar content.
- `test_builder_of_reads_the_sidecar` + `test_builder_of_returns_none_for_a_missing_day` (a person's mistake: asking about a day with no brief).
- `test_build_skips_when_gate_is_closed` — `should_run()` False → no file, no sidecar.
- `test_build_writes_and_records_reason_when_gate_is_open` — the positive path (#600 only tested the "gate closed" side of `build()`; the "gate open, actually writes with the real reason string" path needs its own test so "logs why" is actually verified, not just asserted never to happen).
- `test_build_called_with_explicit_parameters` — `should_run()` is invoked with `usual_hour=9, usual_minute=15` (regression guard on the schedule contract between `morning_brief.py` and its plist).

**`lib/tests/test_health_checks.py`** (add to existing file):
- `test_check_brief_builder_reports_the_machine` (green).
- `test_check_brief_builder_yellow_when_nothing_built_yet`.
- `test_job_placement_reflects_the_new_ownership` — `daily-digest`/`research-colony`/`morning-brief` → `"mini"`, the three `*-fallback` keys → `"laptop"`.

**`lib/tests/test_no_hardcoded_home.py`**: no new test (the existing one already fails correctly) — just add `docs/screenshots/vitals-v4/data.js` to `ALLOWED`, matching the existing `brain-map/export_snapshot.py`-class exceptions (a generated snapshot that legitimately captures a live local path as data, not code).

Every new/changed test above is written to fail against the current, unfixed code first and pass once the corresponding implementation step lands, then the full `lib/tests/`, `skills/improve/scripts/tests/`, and `skills/research-colony/scripts/tests/` suites are run to confirm nothing else regressed (in particular the `test_main_short_circuits_when_out_file_exists` fix above).

## Decisions

<!-- marvin:decisions -->
### retire-cross-machine-merge: Retire `cross_machine_merge.py`'s LLM merge step now, or keep it wired as a dormant fallback?
- [ ] A: Retire now — delete `run_merge_authority()` and its call site in `main()`, since with the Mini as sole primary it will run zero times on any normal day (the laptop never builds its own copy to merge). Keep the item-sync functions (`sync_research_feed`/`sync_qa_knowledge`/`sync_paper_knowledge`) untouched — those still run and matter.
- [ ] B: Keep it wired, unchanged — it's a correct no-op-by-construction safety net for the rare case where both machines genuinely produced their own copy the same day (e.g. a manual run, or a future third machine), and deleting it now is premature given the broader Mac-mini-as-primary-host migration (PRD #109) isn't finished.

## Task List

1. `lib/brief_fallback.py` (new): `Decision` NamedTuple, `_infer_remote_path()`, `read_remote()` (`$HOME/`-prefix split + `shlex.quote()` of the remainder), `produced()`, `past_deadline()`, `should_run()` — importing `is_primary` from `lib/scanner_role.py` and `SSH_OPTS` from `lib/task_dispatch.py`.
2. `lib/tests/test_brief_fallback.py` (new): the full test list above.
3. `skills/improve/scripts/daily_digest.py`: add the gate at the top of `main()` (`usual_hour=8, usual_minute=30`) and the pre-write TOCTOU recheck via `brief_fallback.produced()`.
4. `skills/improve/scripts/tests/test_daily_digest.py`: **add** the three new gate/TOCTOU tests and **fix** `test_main_short_circuits_when_out_file_exists` to mock `should_run`.
5. `skills/research-colony/scripts/run_colony.py`: add the gate at the top of `main()` (`usual_hour=9, usual_minute=0`), gating the whole fetch→correlate→digest pipeline.
6. `skills/research-colony/scripts/research_digest.py`: swap `out_path.exists()` for `brief_fallback.produced(out_path)` in `generate()`, plus a pre-write TOCTOU recheck.
7. `skills/research-colony/scripts/tests/` (new dir): `test_run_colony.py`, `test_research_digest.py` per the test list above.
8. `lib/morning_brief.py`: make `write()` idempotent (return early if today's file exists) and write a `.built-by` sidecar via `machine_profile.machine_label()`; add `build()` (gate via `brief_fallback.should_run(usual_hour=9, usual_minute=15)` then `write()`); add `builder_of(day)`; switch the CLI's `build` subcommand to call `build()` instead of `write()`.
9. `lib/tests/test_morning_brief.py`: add the six tests above.
10. `lib/health_checks.py`: update `JOB_PLACEMENT` (`daily-digest`/`research-colony`/`morning-brief` → `"mini"`; add `daily-digest-fallback`/`research-colony-fallback`/`morning-brief-fallback` → `"laptop"`); add `check_brief_builder()` and wire it into `default_checks()`.
11. `lib/tests/test_health_checks.py`: add the three tests above.
12. `lib/cron_health.py`: add a `"morning-brief": ("09:15", [".claude/logs/morning-brief.log", ".claude/logs/morning-brief-error.log"])` entry to `JOBS` (the Mini now runs this job, where `cron-health` itself runs).
13. Plists: update comments on `skills/improve/com.marvin.daily-digest.plist` and `skills/research-colony/com.marvin.research-colony.plist` to say Mini-primary; move `config/launchd/com.marvin.morning-brief.plist` to 09:15/Mini-only; add three new fallback plists (`skills/improve/com.marvin.daily-digest-fallback.plist` @ 09:30, `skills/research-colony/com.marvin.research-colony-fallback.plist` @ 10:00, `config/launchd/com.marvin.morning-brief-fallback.plist` @ 10:15), each laptop-only per their comments.
14. `CONTEXT.md`'s "Brief owner" bullet: replace with the three concrete schedules (Mini primary / MacBook fallback times) and a correct, non-overstated note that `cross_machine_merge.py`'s LLM step is currently wired but runs zero LLM calls on a normal day, with retiring it tracked as this PR's `retire-cross-machine-merge` Decision.
15. `lib/tests/test_no_hardcoded_home.py`: add `"docs/screenshots/vitals-v4/data.js"` to `ALLOWED` (pre-existing, unrelated merge-gate blocker found while verifying this ticket; fixed in-scope per "own the whole system").
16. If Decision `retire-cross-machine-merge` is answered **A** before this lands: delete `run_merge_authority()` and its call in `cross_machine_merge.py::main()`, and the corresponding tests in `skills/improve/scripts/tests/test_cross_machine_merge.py`; otherwise leave that file untouched.
17. Run the full `lib/tests/`, `skills/improve/scripts/tests/`, `skills/research-colony/scripts/tests/` suites; confirm every new/changed test fails on the pre-change code and passes after, and that nothing else regresses.