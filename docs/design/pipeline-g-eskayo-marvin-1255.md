## North-star fit

**Reuses before adding anything new:**
- `lib/dispatch_concurrency.py`'s already-built reap pipeline (`slots_in_use`/`slots_in_use_remote`/`partition_alive`/`_read_task_records`/`_reap`) is the exact "is this machine really busy" primitive `device_status.py`'s `local()`/`remote_slots_reader()` (lines 117-134) already uses to get a truthful busy signal instead of trusting the raw flag. `task_dispatch.select_machine` is the one place that still trusts the raw `dispatch-state.json` `"busy"` boolean directly — this plan points it at the same already-tested primitive instead of adding a second one.
- `lib/health_checks.py`'s `check_sync_stuck` + `_run_sync_log_remote` + `_reachable` (lines 213-340) is the existing pattern for "the same per-machine judgment, run locally and over SSH on every reachable device, folded into one list of rows." `check_dispatch_lock` already has the right judgment (age vs. `MAX_DISPATCH_MINUTES_YELLOW`/`RED`) but only for `localhost`; this plan fans the same judgment out with the same pattern instead of inventing a new cross-machine mechanism.
- `lib/error_log.py`'s `record()` is the existing "one error log Health already reads" (already reused by `hook_errors.py`) — reused for the ticket's "log one error row," not a new log file.
- `lib/stamped.py`'s `write()` (temp file + `os.replace`) is the existing atomic-write precedent in this codebase; the bash wrapper's task-record write adopts the same temp+rename principle at the shell level (Python's `os.replace` isn't available inside the dispatched bash script).
- `lib/host_os.py` is already the single place "anything that differs between macOS and Linux" is answered (`tailscale_bin`, `lsof_bin`); boot time is added there rather than duplicated per-caller.

**Simplicity:** no new files, no new log, no new daemon. Six existing modules get a function each (mostly additive, two signature changes limited to one call site each), reusing primitives that already exist and are already tested for an adjacent purpose (UI display). This is the Colton-check form: the underlying principle ("don't trust a cached flag that can outlive the process it describes") already has a correct implementation for the dashboard; dispatch just wasn't wired to it.

**Tokens:** spends a small, fixed amount of implementation now; saves recurring debugging/triage tokens later — this exact failure mode (a machine silently skipped for weeks) cost a live investigation once already (the ticket's own "Purpose" section) and would otherwise recur silently.

**Phone-OS direction:** reliability precondition (north star 2: "nothing may break silently") — a machine that silently stops getting work is exactly the kind of silent failure that direction can't tolerate.

**Machine:** no change — this runs identically on whichever Mac/box dispatches or is dispatched to; the fix is in logic every machine already runs.

**North star 5 fit, corrected:** the ticket's own "Purpose" line cites north star 5 for the *problem*, but the fix is squarely north star 2 ("nothing may break silently") and the reliability precondition it names — north star 5 (load balancing) doesn't argue for or against this change either way, since a machine that's wrongly marked busy isn't an *overload* problem, it's a *correctness* problem in what "busy" means. Framing it as 5 is imprecise; 2 is the one actually in play.

**More capable, not more passive:** this is pure reliability plumbing — it removes a failure mode, it doesn't automate a decision a person was making. Clear net gain, no north star argues against it.

No decisions needed for the owner — every acceptance criterion is mechanical (a liveness/atomicity bug fix), nothing here is a design choice between live options.

## Tests to write first

Mapped to the ticket's ACs and "how we'll try to break it" list, plus misuse the section didn't name:

1. **Corrupt record isn't counted as running, and is moved aside** (AC1)
   - `_read_task_records` quarantines a malformed-JSON file into `stale-records/` (not silently dropped) and logs one `error_log.record` call.
   - `_reap` quarantines (not deletes) a dead-pid record, same logging.
   - Existing `test_read_task_records_globs_json_files_and_skips_malformed` and `test_reap_unlinks_dead_record_files` updated to assert quarantine-not-delete (monkeypatching `STALE_RECORDS_DIR` and stubbing `error_log.record` so no test touches the real home).

2. **Busy from a dead process, or from before the last boot, doesn't block `select_machine`** (AC2 + the reboot/PID-reuse attack)
   - `_pid_alive(pid, started_at)`: false when the pid doesn't exist at all.
   - `_pid_alive`: false when `started_at` predates the injected `boot_time` (deterministic boot check, independent of `ps`).
   - `_pid_alive`: false when the pid exists but its OWN process-start time (injected) doesn't match `started_at` within tolerance — the PID-reuse-after-reboot attack named explicitly in the ticket.
   - `_pid_alive`: true when process start matches within tolerance; true when no `started_at` given (legacy record, pid-liveness only); true on `PermissionError` (can't inspect further, must not guess dead); true when `ps` can't be read (can't tell, must not guess reused).
   - `_process_start_time`: parses `ps -o etimes=` output; returns `None` on nonzero exit / bad output (never raises, never guesses).
   - `host_os.boot_time()`: parses macOS `sysctl -n kern.boottime` and Linux `/proc/uptime`; `None` on any failure or unknown OS.
   - `select_machine`: with the local flag stale-busy but no live record, the local machine is still selected; with a live record, it's correctly skipped.
   - `select_machine`: same two cases for a remote device, reusing `slots_in_use_remote` ("the same rules" over SSH, since that call runs the identical reap/liveness code *on* the remote machine, not here).

3. **A killed run leaves the machine selectable on the next scan** (AC3)
   - Integration-style: write a task record with a genuinely dead pid and an old `started_at`; `_locally_busy()` (new helper) reads false; `select_machine()` picks the local machine on the next call with no manual cleanup step.

4. **Records are written atomically** (AC4)
   - Wrapper-script text asserts the task-record write goes to a `task_id`-qualified temp path then `mv`s to the final path (never a bare `>` into the final path).
   - Execution test: running only the "write temp file" half of that line (simulating a crash before the `mv`) leaves no file at all at the final path — "no partial file," literally.
   - Concurrency test: two different `task_id`s' write-fragments run concurrently (threads) land in two distinct, individually-complete files — proves the temp name includes `task_id` (not a shared `.tmp`), so two dispatches writing at once can't corrupt each other.

5. **Health row for a machine stuck busy past the longest expected run** (bullet 4 of "What to build")
   - `check_dispatch_lock_remote`: green when a reachable remote's lock is idle or freshly busy; yellow/red at the same age thresholds `check_dispatch_lock` already uses locally; one `_unknown` row (never silently green) when SSH fails; skips an unreachable device per `_reachable`.
   - Existing local `check_dispatch_lock` tests (green/no-file, green/idle, yellow, red, green/fresh) re-run unchanged against a small `_evaluate_dispatch_lock` extraction, proving the refactor didn't change local behavior.

6. **Misuse not named in the ticket's list, added per north-star principle ("tests try to break it"):**
   - Missing `pid` key, or `pid: null`, in an otherwise-valid record → dead, not alive (already covered by an existing test; kept passing through the signature change).
   - Unparseable `started_at` string → treated as "can't tell," pid-liveness only (never crashes `select_machine`).
   - `slots_in_use_remote` unreachable (SSH failure) → `select_machine` falls back to today's fail-open behavior (not busy), unchanged.

## Task List

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