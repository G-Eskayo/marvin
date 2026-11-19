1. `lib/host_os.py`: add `boot_time(run=None, read_uptime=None) -> datetime | None` (macOS via `sysctl -n kern.boottime`, Linux via `/proc/uptime`, `None` otherwise); tests in `lib/tests/test_host_os.py`.
2. `lib/dispatch_concurrency.py`:
   - Add `PID_START_TOLERANCE_S`, `_process_start_time(pid, run=None)`, and rewrite `_pid_alive(pid, started_at=None, *, process_start=None, boot_time=None)` to check process existence, boot-time predating, and process-start-time match.
   - Update `partition_alive` to call `is_alive(pid, rec.get("started_at"))`.
   - Add `STALE_RECORDS_DIR` and `_quarantine(path, reason, raw="")` (move + `error_log.record`), and switch `_read_task_records` (corrupt JSON) and `_reap` (dead records) to call it instead of silently skipping / unlinking.
   - Update existing tests for the new 2-arg `is_alive` contract and quarantine-not-delete behavior; add the new `_pid_alive`/`_process_start_time`/quarantine tests from the list above.
3. `lib/task_dispatch.py`:
   - Add `_locally_busy()` and `_remotely_busy(host, device_id)` built on `dispatch_concurrency.slots_in_use`/`slots_in_use_remote`.
   - In `select_machine`, replace the raw `_read_local_dispatch_state()`/`_read_remote_dispatch_state()` busy checks with these two (leave both legacy readers in place — `ticket_pipeline.py` and `device_status.py` still use them for their own, unrelated purposes).
   - In `_build_wrapper_script`, change the task-record `printf > file` to `printf > tmp && mv tmp file`, and add the temp file to the EXIT trap's `rm -f`.
   - Add the new `select_machine`/`_locally_busy`/`_remotely_busy`/wrapper-atomicity tests from the list above to `lib/tests/test_task_dispatch.py` and `lib/tests/test_task_dispatch_wrapper_script.py`.
4. `lib/health_checks.py`:
   - Extract `_evaluate_dispatch_lock(state, now)` from `check_dispatch_lock`'s body (no behavior change).
   - Add `_run_dispatch_state_remote(host)` (mirrors `_run_sync_log_remote`) and `check_dispatch_lock_remote(reachability=None, remote=None) -> list[dict]`.
   - Register it in `default_checks` next to the existing `"dispatch:lock-age"` entry.
   - Add the cross-machine tests from the list above to `lib/tests/test_health_checks.py`; confirm the existing local `check_dispatch_lock` tests still pass unchanged.
5. Run the full `lib/` test suite (not just the affected files) before calling this done, per the merge gate's own rule.