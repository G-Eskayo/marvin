## North-star fit

**Reuses, before adding anything new:**
- `stamped.write()` (`lib/stamped.py:91`) — already does temp-file-then-`os.replace` atomic writes; I extend this same technique by hand in the bash wrapper (no `os.replace` there, but `mv` is the shell equivalent) instead of inventing a second atomicity convention.
- `dispatch_concurrency.partition_alive` / `slots_in_use` / `refresh_dispatch_state_summary` (`lib/dispatch_concurrency.py:247-300,364-379`) — reap-on-read for local task records already exists; I extend it (move-aside + log, process-start-time cross-check) rather than writing a second reaper in `task_dispatch.py`.
- `health_checks.check_dispatch_lock` (`lib/health_checks.py:119`, ADR 0033) — already the "stuck busy flag" health row from the *last* time this exact failure mode bit (15 days stuck, 2026-10-01). Extends it rather than adding a second health check for the same thing.
- `health_checks.check_sync_stuck`'s cross-machine SSH iteration pattern (`lib/health_checks.py:316-340`: `[(me, None)] + remote_devices()`, `_reachable(reachability, dev)`, `_unknown(...)` row on failure) — the established shape for "a health row that covers every machine, not just this one." I reuse it verbatim for `check_dispatch_lock` instead of inventing a new cross-machine pattern.
- `hook_errors.log_hook_error` / `task_dispatch._log_hook_error_safe` — the existing "one error row" logger, for the "log one error row" requirement on reaped records.
- `dispatch_concurrency.slots_in_use_remote` (ssh → the remote's own `dispatch_concurrency.py` CLI) — already the pattern for "apply this machine's own rules on a remote machine by running the same code there over ssh," reused for `_read_remote_dispatch_state` and `machine_load`'s remote branch instead of the current raw `ssh ... cat` / `ssh ... ls | grep -c`.

**Simplest sufficient approach:** the three symptoms in the ticket (corrupt `"pid": }` record, stuck `busy` flag, "skipped forever") are one root cause — every reader trusts whatever's on disk instead of deriving it from live process state at read time, and every writer isn't atomic. One chokepoint fix (`refresh_dispatch_state_summary()`, already reap-on-read, called *before* every read instead of only by the wrapper script at task start/exit) plus one atomicity fix (temp+rename everywhere a record is written) closes the whole incident, rather than patching `select_machine` alone and leaving `device_status.py`/the dashboard/the health check with the same stale-read bug.

**Where it saves tokens:** none of this needs a new daemon, lock file, or polling loop — it's read-time self-healing using data already being written (`started_at`, `pid`), so no new state has to be invented or kept in sync.

**Phone-OS direction:** directly serves north star 5 (every machine works, none skipped silently) and north star 2 (nothing breaks silently) — a machine that's actually free must never look permanently busy to the rest of the fleet.

**More capable, not more passive:** this is pure reliability plumbing; it doesn't change what a person does, it removes a failure mode nobody should have to notice or hand-fix (Gil had to SSH in and move the corrupt files by hand — that's exactly the kind of silent, manual-recovery failure this closes).

**Prior attempt:** the issue's one comment says a previous automated pass returned "mixed" after 3 iterations, but no branch, WIP commit, or PR survives for it (checked `git log --all`, `gh pr list --search 1255` — nothing). This plan is a fresh design from the ticket text and the current code, not a patch of that attempt.

## Tests to write first

*Ticket's "How we'll try to break it":*
1. **PID reused after reboot**: a task record with `pid=<N>`, `started_at=<old ISO time>`; fake "process `N` is alive" (`is_alive` stub) but fake "process `N`'s actual start time" far from `started_at` → record classifies dead, moved to `stale-records/`, reason logged.
2. **Two dispatches writing at once**: two wrapper-script runs started back-to-back (or concurrently) on the same machine write two distinct `{task_id}.json` files; `dispatch-state.json`'s final `busy` is **derived from both alive records** (earliest `started_at` wins), not stomped by whichever wrapper's EXIT trap happens to run last.
3. **Remote read over ssh, same rules**: `_read_remote_dispatch_state`/`device_status.probe_remote`/`machine_load`'s remote branch all run the *same* refresh-then-read command as the local path (one ssh round trip) — test the shell command string built, and a fake ssh transport that returns a corrupt/empty state.

*Ticket's acceptance criteria:*
4. A corrupt record (`{"pid": }` truncated JSON, and a few other malformed shapes — truncated mid-object, not JSON at all, a `.json` file that's a directory) doesn't count as running (`slots_in_use`/`_live_task_count` excludes it) and is moved to `~/.claude/dispatch/stale-records/` with a reason file/log row, not silently skipped.
5. `busy=True` with `pid` of a dead process → `select_machine` does not skip the machine. `busy=True` with `started_at` before `host_os.boot_time()` (process genuinely gone, machine rebooted) → not skipped either, even if by coincidence something currently holds that pid.
6. A killed run (`os.kill(pid, SIGKILL)` on a real forked child in-test, no EXIT trap fires) leaves the task record behind; next `select_machine()` call still selects the machine (because the record is reaped as dead-pid at read time, not because the trap ran).
7. Atomic record write: run the real wrapper script, `kill -9` the subprocess mid-write (simulate by truncating/corrupting the would-be temp file before rename, and by checking no `*.json.tmp` file is ever left in the final directory after a normal run) → tasks dir never contains a half-written `{task_id}.json`, and the record never appears without its `pid`.

*Misuse the section didn't list, that I'm adding:*
8. Empty task record file (`0` bytes) and a huge one (multi-MB garbage) — both treated as corrupt/dead, not an exception that aborts the whole sweep (matches existing `check_sync_stuck`'s "one ssh timeout must not kill the whole sweep" norm).
9. `stale-records/` directory itself missing, unwritable (permission error), or on a different filesystem than `tasks/` (cross-device `rename` fails) — the move degrades to "delete and log," never raises out of `slots_in_use`.
10. `host_os.boot_time()` / `process_start_time()` unreadable (bad `sysctl`/`ps` output, missing binary) → treated as "unknown," never used to *demote* an otherwise-alive record (an unreadable guard must never block — matches `dispatch_concurrency._safe`'s existing norm).
11. `dispatch-state.json` hand-edited by a person into something that isn't a JSON object, or missing entirely, while a real alive task record exists → `refresh_dispatch_state_summary()` still rebuilds a correct `busy: true` from the task record, not from the broken state file.
12. A machine with **zero** task records but a `dispatch-state.json` saying `busy: true` (orphaned flag, no record at all — the exact "flag written, crash before any record existed" case) → refresh clears it to `busy: false`.
13. `select_machine` called while the remote ssh call to refresh+read times out or the host is unreachable mid-call → treated as unavailable (today's existing behavior), not as "busy forever" and not as a crash.
14. Fallback-run markers (`FALLBACK_RUNS_DIR`, no `task_id` field) go through the same reap path without a `task_id` → must key off the record's own file path, not a `task_id` lookup (today's `_reap` assumes `task_id` exists; this breaks for fallback markers once `_live_task_count` is unified onto the same reaper).
15. `check_dispatch_lock` extended cross-machine: one reachable remote with a genuinely stuck lock → red/yellow row named for that machine; one unreachable remote → one "couldn't measure" row, never a crash that drops every other check (same norm as `check_sync_stuck`).

**Changed, not new** — `lib/tests/test_dispatch_concurrency.py::test_reap_unlinks_dead_record_files` (line 168) currently pins "unlink." That test gets rewritten to assert "moved to stale-records/ with a reason," per the ticket's explicit requirement — Verify will see this as a test changing alongside the code it pins, which is the intended, not accidental, case.

## Design

1. **`lib/host_os.py`** — add `boot_time(run=None) -> datetime | None` (macOS: `sysctl -n kern.boottime`, parse `sec = N`; Linux: `/proc/stat`'s `btime` line) and `process_start_time(pid: int, run=None) -> datetime | None` (`ps -o etimes= -p PID`, both OSes support it, avoids locale-dependent `lstart` date parsing). Both return `None` on any failure — never raise, never used to fail-closed per existing `_safe()` norm.
2. **`lib/dispatch_concurrency.py`**:
   - `_read_task_records` returns `(path, record_or_None, error_or_None)` triples instead of silently dropping malformed files.
   - `partition_alive` unchanged in signature (keeps `is_alive(pid)` contract, doesn't break existing simple tests); add a second pass `_demote_reused_pids(alive_with_paths, now, process_start=host_os.process_start_time, boot_time=host_os.boot_time)` that moves anything whose actual process start time doesn't match `started_at` within `TASK_RECORD_TIME_TOLERANCE_S` (30s), or whose `started_at` predates `boot_time()`, from alive into dead.
   - `_reap` keyed by each record's own file path (not reconstructed from `task_id`) and a `reason` string; moves the file into `STALE_RECORDS_DIR = ~/.claude/dispatch/stale-records/` (renaming on collision), falls back to delete-and-log if the move fails (permissions, cross-device), and logs one row via a new small `hook_errors.log_safe()` (factored out of `task_dispatch._log_hook_error_safe`, reused from both modules).
   - `refresh_dispatch_state_summary` unchanged in shape, now benefits from the above automatically since it calls `slots_in_use`.
   - `_fallback_runs_in_progress`/fallback markers route through the same reader (works once `_reap` is path-keyed, not `task_id`-keyed).
3. **`lib/task_dispatch.py`**:
   - `_live_task_count` delegates to `dispatch_concurrency.slots_in_use(tasks_dir=tasks_dir)` (removes the duplicate pid-only check, gets reap-and-move-aside for free).
   - `_read_local_dispatch_state()` calls `dispatch_concurrency.refresh_dispatch_state_summary()` before `stamped.read(...)`.
   - `_read_remote_dispatch_state(host)` and `machine_load`'s remote branch combine "refresh then read/count" into one ssh call (factor the shared command string into one helper both use), instead of raw `cat`/`ls | grep -c`.
   - `_build_wrapper_script`: task-record `printf` writes to `{tasks_dir}/{task_id}.json.tmp` then `mv` to the final name; `dispatch-state.json` busy/idle heredocs write to `{state}.tmp.$$` then `mv`; the `FALLBACK_RUNS_DIR` marker write in `_fall_back` gets the same temp+rename treatment.
4. **`lib/device_status.py`**: `probe_remote` uses the same shared "refresh then cat" ssh command as `task_dispatch._read_remote_dispatch_state`, keeping its own "unreachable → None" policy on top.
5. **`lib/health_checks.py`**: `check_dispatch_lock` becomes cross-machine using the exact `check_sync_stuck` iteration shape (self + each reachable remote device over ssh running the same local check remotely), id/label updated (`dispatch:lock-age` → one row per machine, `"Dispatch lock — {machine}"`), budget moves to `CROSS_MACHINE_BUDGET_S`.

No Decisions section — every fork above was resolved by an existing, precedented pattern already in this codebase, not an open product choice.

## Task List

1. Add `host_os.boot_time()` and `host_os.process_start_time(pid)`, with tests for sysctl/ps-output parsing and "unreadable → None".
2. Rework `dispatch_concurrency._read_task_records` to surface `(path, record, error)` instead of silently dropping malformed files; update its tests.
3. Add the process-start-time/boot-time demotion pass and wire it into `slots_in_use`; add `hook_errors.log_safe()` and the `stale-records/` move-or-delete-and-log `_reap`; update/replace `test_reap_unlinks_dead_record_files`.
4. Unify `task_dispatch._live_task_count` onto `dispatch_concurrency.slots_in_use`; verify `_fallback_runs_in_progress` still works with path-keyed reaping (no `task_id` on fallback markers).
5. Make `task_dispatch._read_local_dispatch_state` call `refresh_dispatch_state_summary()` before reading; add the matching remote "refresh then read/count" ssh helper and use it from `_read_remote_dispatch_state` and `machine_load`'s remote branch.
6. Make task-record and dispatch-state writes in `_build_wrapper_script`, and the fallback marker write in `_fall_back`, atomic (temp file + `mv`); add the wrapper-script subprocess tests that assert no `.tmp` leftovers and no record without a `pid`.
7. Update `device_status.probe_remote` to use the shared remote refresh-then-read command.
8. Extend `health_checks.check_dispatch_lock` to the cross-machine `check_sync_stuck` shape; add its tests (reachable-and-stuck, reachable-and-fine, unreachable).
9. Run the full misuse list above (items 8–15) as tests, not just the ticket's four ACs, before calling this done.
10. Full local test suite (Python + dispatch-specific) green; manual smoke: run the real wrapper script end-to-end once, confirm `~/.claude/dispatch/tasks/*.json` and `~/.claude/dispatch-state.json` round-trip correctly on this machine.