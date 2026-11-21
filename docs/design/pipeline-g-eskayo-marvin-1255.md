## North-star fit

Reuses, rather than invents: `dispatch_concurrency.slots_in_use`/`partition_alive`/`_reap`/`refresh_dispatch_state_summary` (already live-record-driven and already atomic for the summary file via `stamped.write`), `stamped.write`'s temp+rename pattern (mirrored in bash for the task record), `health_checks.py`'s existing `check_dispatch_lock` (already the right health-row shape, just local-only) and its `check_sync_stuck`/`check_pipeline_breaker`/`check_recent_errors` cross-machine pattern (`_reachable(reachability, dev)` + injectable `remote`), `_ETIME_AWK`'s proven `ps -o etime=` elapsed-time trick (already solved the "macOS `ps` has no `etimes`" problem once — reused instead of inventing a `sysctl kern.boottime`/`/proc/stat` primitive), and `hook_errors.log_hook_error` (which already feeds the "Recent errors" health card, so one call satisfies both "log one error row" and general visibility). The only genuinely new code is: the bash temp-file+rename for the task record, the `process_started_at` reuse check, and extending two existing functions (`check_dispatch_lock`, `readDispatchStatus`) to more inputs.

Root cause, precisely: `task_dispatch.select_machine` (and `ticket_pipeline._flag_busy`, which calls the same function) trusts the raw `dispatch-state.json` `busy` flag — written once at job start and cleared only by that job's own `EXIT` trap — instead of asking "is a process actually alive for this." A crash skips the trap, so `busy: true` survives forever. `dispatch_concurrency.refresh_dispatch_state_summary()` *already* derives busy correctly from live records, but nothing calls it before `select_machine` trusts the file. Fix at that exact choke point (`task_dispatch._read_local_dispatch_state` / `_read_remote_dispatch_state`), not by rewriting machine selection.

Cost: no new ssh round-trips (the remote fix folds a `refresh-summary` call into the existing single ssh read); a couple of cheap local syscalls (`ps -o etime=`) only on the production path, never in unit tests (kept opt-in at the low level, defaulted-on at the orchestration/CLI layer, matching the `is_alive` injection convention already used throughout `dispatch_concurrency.py`). Leaves the user more capable: a crashed machine heals itself within one scan instead of silently sitting idle for weeks, with a dashboard/Health row that would have caught the real 2026-11-10 incident in minutes.

## Tests to write first

**Corrupt/dead records (`lib/tests/test_dispatch_concurrency.py`)**
1. A malformed record (`"pid": }`, the exact incident string) is not counted by `slots_in_use`/`_read_task_records`, and the file is moved to `stale-records/` (not deleted) — no change needed to the existing `test_read_task_records_globs_json_files_and_skips_malformed` (its contract is unaffected; new assertions added for the move).
2. A dead-pid record is reaped into `stale-records/` (update `test_reap_unlinks_dead_record_files`/`test_slots_in_use_reads_and_reaps_dead_and_filters_by_machine` assertions from "file gone" to "file moved, not deleted," they already only assert non-existence at the old path so this is additive).
3. One error row is logged (via `hook_errors.log_hook_error`) per corrupt/dead record moved.
4. `partition_alive(records, is_alive, process_started_at=fake)`: a pid that's alive but whose fake start-time is *after* the record's `started_at` (+ slack) is classified dead ("pid reused after reboot"); a pid alive with start-time *before* `started_at` stays alive; `process_started_at=None` (default) reproduces today's exact behaviour — the two existing `partition_alive` tests need no changes.
5. `refresh_dispatch_state_summary` with a dead-pid record (fake `process_started_at`) produces `{"busy": False}`; update `test_refresh_dispatch_state_summary_busy_when_records_exist` to pass an explicit `process_started_at=lambda pid: None` so it stays deterministic under the new default.
6. `_process_start_time(pid)` parses real `ps -o etime=` output into a `datetime` (one direct test against the real `ps`, mirroring `test_the_machine_script_reads_a_real_process_uptime_with_this_machines_ps`'s use of a real spawned `sleep` child) and returns `None` for a pid that doesn't exist.

**`select_machine` no longer trusts a stale/wrong busy flag (`lib/tests/test_task_dispatch.py`)**
7. Local: `dispatch-state.json` says `busy: true` for a task whose pid is dead → `select_machine()` still picks this machine (AC2/AC3, using real tmp dirs + a real-but-exited pid, e.g. spawn and wait a subprocess).
8. Local: same, but the pid is alive (reused) and its real start time is after the record's `started_at` → still selectable (AC2's reboot-reuse case), via injected `process_started_at`.
9. Local: a genuinely running task (real live subprocess, started_at just now) → machine is correctly reported busy (no regression / false negative).
10. Remote: `_read_remote_dispatch_state` runs `refresh-summary` before `cat`-ing the state file — assert on the ssh command string, and that stdout parsing/error-handling tests already in the file (ssh failure, bad JSON, timeout, etc.) are untouched by the command-string change (no edits expected, since they monkeypatch `subprocess.run`'s return value, not the command).
11. "A killed run leaves the machine selectable on the next scan": integration-style — write a task record for a pid that's spawned then killed, mark `dispatch-state.json` busy, call `select_machine` again after the kill and assert the machine returns.

**Atomic task-record write (`lib/tests/test_task_dispatch.py`, mirroring `test_the_wrapper_really_marks_busy_and_idle_under_the_running_home`'s real-bash style)**
12. The record-write line in `_build_wrapper_script`'s output writes to a `.tmp` path and only then `mv`s it into place.
13. Running only the "write the temp file" half of that line (simulating a crash before the `mv`) leaves no file at the final `{task_id}.json` path, only the `.tmp` one.
14. Running the full line produces a valid, parseable final record with the right `pid`.
15. Two different `task_id`s writing concurrently (two separate wrapper invocations, real subprocesses) never collide on the same temp filename and both final records end up correct (misuse: concurrency).

**Reaping over SSH, "the same rules" (`lib/tests/test_health_checks.py` / `test_dispatch_concurrency.py`)**
16. `dispatch_concurrency.slots_in_use_remote`/the CLI's `count-in-use` (new) is exercised with a fake `run` returning a corrupt or dead-pid record remotely, and the parsed count reflects the reap, not the raw file count — covers `task_dispatch.machine_load`'s remote branch (the "slot counts" bullet) with a fake ssh `run`.

**Dashboard reader (`dashboard/test/dispatch_status.test.js`)**
17. `readDispatchStatus` reports `busy: false` when the state file says busy but the referenced task record's pid is dead or the record is missing/malformed (update the existing file to add a `tasksDir` fixture per `withTempFile`'s pattern; none of the 5 existing tests change since they never populate a task record, so a missing record for `task_id: 'abc'` must keep today's result when the task_id is absent — verify that edge explicitly so a legitimate busy state isn't quietly swallowed just because the dashboard's tasksDir override wasn't given in older call sites).

**Health row across machines (`lib/tests/test_health_checks.py`)**
18. `check_dispatch_lock` returns a list; update the 4 existing tests (`test_check_dispatch_lock_green_when_no_file`, `_green_when_idle`, `_red_after_15_days`, `_yellow_in_warning_window`, `_green_shortly_after_start`) to index the local row and to stub `machine_profile.remote_devices` to `{}` (matching `check_pipeline_breaker`'s test convention) so they stay hermetic.
19. A remote Mac's dispatch-state.json (read via a fake `remote(host)`, reachable) shows its own red/yellow row at `dispatch:lock-age@{dev}`, independent of the local machine's state.
20. An unreachable remote Mac produces one "can't check" row, never a crash of the whole check (mirrors `check_sync_stuck`'s per-device isolation).

**Misuse not explicitly named in the ticket, added per the standing adversarial-TDD rule**
21. Empty/zero-byte task record file → treated as malformed, quarantined, not counted (not just a `json.JSONDecodeError` on `{not json}`).
22. A `stale-records/` directory that doesn't exist yet is created on first use; a `stale-records/` move that fails (e.g. permissions) degrades to "leave the dead record in place, log the failure" rather than raising and killing the whole scan.
23. `FALLBACK_RUNS_DIR`'s own records (which lack `task_id`) pass through the shared reap path as a safe no-op (no exception, no accidental deletion) now that `task_dispatch._live_task_count` delegates to `dispatch_concurrency.slots_in_use` — covers the "wrong record shape in a shared code path" misuse case.
24. A record whose `pid` is present but non-integer / negative (a person's mistake, hand-edited file) is treated as dead, not as a crash in `partition_alive`/`_process_start_time`.

## Decisions
<!-- marvin:decisions -->
### retention: Should `~/.claude/dispatch/stale-records/` ever be cleaned up automatically?
- [ ] A: No automatic cleanup for now — matches your own manual move on 2026-11-10; revisit only if it grows large
- [ ] B: Add a cheap age-based prune (e.g. delete anything older than 30 days) as part of this ticket
- [ ] C: Leave it unmanaged here, but file a follow-up ticket to add pruning later

## Task List

1. `lib/dispatch_concurrency.py`: add `_process_start_time(pid) -> datetime | None` (via `ps -o etime= -p PID`, reusing `health_checks._ETIME_AWK`'s elapsed-seconds math, ported to Python); add `REUSE_SLACK_S`.
2. `lib/dispatch_concurrency.py`: extend `partition_alive(records, is_alive, process_started_at=None)` with the reuse check (default `None` = today's behaviour, unchanged for direct callers).
3. `lib/dispatch_concurrency.py`: add `_quarantine_stale(src, tasks_dir, reason)` (move into `tasks_dir.parent / "stale-records"`, log via `hook_errors.log_hook_error`); wire it into `_read_task_records` (malformed JSON) and `_reap` (dead records, replacing the unlink).
4. `lib/dispatch_concurrency.py`: thread `process_started_at` through `slots_in_use` (default: the real `_process_start_time`) and `refresh_dispatch_state_summary` (default: `None`, i.e. unchanged unless a caller opts in).
5. `lib/dispatch_concurrency.py`: `refresh-summary` CLI branch passes `process_started_at=_process_start_time` explicitly (the real production wiring); add a `count-in-use [--machine ID]` CLI branch (prints `len(slots_in_use(...))`).
6. `lib/task_dispatch.py`: rewrite `_read_local_dispatch_state` to call `dispatch_concurrency.refresh_dispatch_state_summary(process_started_at=dc._process_start_time)` then read `dc.DISPATCH_STATE_PATH` via `stamped.read`.
7. `lib/task_dispatch.py`: rewrite `_read_remote_dispatch_state` to ssh `refresh-summary` (output silenced) then `cat {SHELL_STATE_PATH}` in one call, keeping existing JSON-parse/error-handling unchanged.
8. `lib/task_dispatch.py`: rewrite `_live_task_count` to delegate to `dispatch_concurrency.slots_in_use(tasks_dir=tasks_dir)`; delete the now-unused `task_dispatch._pid_alive`.
9. `lib/task_dispatch.py`: `machine_load`'s remote branch: replace `ls {SHELL_TASKS_DIR} | grep -c '\.json$'` with the new `count-in-use` CLI call.
10. `lib/task_dispatch.py`: `_build_wrapper_script` — write the task record to a `.{task_id}.json.tmp` file then `mv` it into place; also `rm -f` that tmp path in the `EXIT` trap.
11. `lib/health_checks.py`: split `check_dispatch_lock`'s scoring into `evaluate_dispatch_lock(text, now)`, then rewrite `check_dispatch_lock(state_path=None, reachability=None, remote=None, now=None)` to return a list (local row + one row per reachable remote Mac, reusing `_reachable`/the `check_sync_stuck`-style remote-ssh pattern); update its `default_checks()` registration to `CROSS_MACHINE_BUDGET_S`.
12. `dashboard/electron/main/dispatch_status.js`: `readDispatchStatus` cross-checks the referenced task record's pid liveness (via `process.kill(pid, 0)`) before trusting `busy: true`; accept an injectable `tasksDir` for tests.
13. Write all tests listed above, confirming each fails against the old code and passes against the new.
14. Run `pytest lib` and the dashboard vitest suite in full (not just the touched files) before calling this done, per the full-suite-before-merge rule.