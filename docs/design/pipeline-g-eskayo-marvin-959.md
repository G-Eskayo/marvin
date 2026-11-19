## North-star fit

- **Reuses, before adding anything new:**
  - The atomic-write pattern already used three ways (`lib/main_health.py:_write`, `lib/stamped.py:write`, `lib/accounts.py` status write) for the new guard-state file — no new persistence idiom.
  - `lib/mr_notification.py:alert_on_change` + the per-feature wrapper shape of `lib/accounts.py:alert_changes`/`sweep_and_alert` for the 2-hour "degraded" alert — this is the one new alert function the design doc (`instance/docs/plans/failure-containment-2026-10-30.md`) says to add; it is a thin wrapper, not new alerting machinery.
  - `health_checks.py`'s existing list-returning check shape (`check_hold_revisit`, `check_missing_profiles`) and its existing generic sweep wiring (`_cli()` → `react_to_accounts()` pattern) for the new Health check and its alert step.
  - The existing `fcntl.flock` sidecar-lock pattern (`memory_guard.py:_queue_lock`, `error_log.py:_append`) for safe concurrent read-modify-write of the one shared guard-state file.
  - The existing ssh-CLI-subprocess pattern (`dispatch_concurrency.credit_ready_remote`, `slots_in_use_remote`) for the new remote-disk probe, and the existing JS→Python subprocess pattern already in `dashboard/webhook-server/merge.js` (it already shells out for disk first aid) for wiring the merge gate's disk floor into the same Python-side state file, so there is one table and one Health row shape for both languages, not two.
- **Simplest sufficient form:** one small module (`lib/guard_reading.py`) holding (a) a `FAIL_MODE` table, (b) a `reading(name, value_or_error)` helper that records streak/since to one small JSON state object (not an unbounded append log — `can_start_another` and similar guards are called many times a minute, so a denormalized per-guard state file keeps this O(1) per call instead of growing a log that needs its own trim logic), and (c) `alert_degraded()` wrapping `mr_notification.alert_on_change`. Every other change is a guard call site growing by one line (wrap the existing `None`-on-failure return in `guard_reading.reading(...)`), plus two real fail-open→fail-closed behavior changes (disk, memory) that the Decision already settled.
- **Where it spends tokens/resources:** one new small file + ~13 one-line call-site edits + one new Health check + one new JS call site. No new polling, no new cron job (the alert rides the existing 15-minute health sweep), no per-call log growth.
- **More capable, not more passive:** this doesn't automate a judgment call away from Gil — it makes guards that are already supposed to protect the system actually say so instead of quietly doing nothing, which is what let #889 run 4 days and #891 run since parallel slots shipped.

**Guards and their fail mode (the table, acceptance criterion #1):**

| Guard name | Call site | Fail mode | Why |
|---|---|---|---|
| `disk:dispatch_local` | `lib/ticket_pipeline.py:_free_disk_gb` (local) | closed | protects the machine |
| `disk:dispatch_remote` | `lib/ticket_pipeline.py:_select_for_profile` (new remote probe, see below) | closed | protects the machine |
| `disk:preflight` | `lib/disk_triggers.py:preflight` (`free_bytes`) | closed | protects the machine |
| `disk:merge_gate` | `dashboard/webhook-server/merge.js:rebaseAndRetest` (`freeDiskBytes`) | closed | protects the machine |
| `memory:pressure` | `lib/memory_guard.py:check` (`read_level`) | closed | protects the machine |
| `github:budget` | `lib/ticket_pipeline.py:_github_budget_pct` | open, loud | not disk/memory |
| `dispatch:breaker` | `lib/dispatch_concurrency.py:can_start_another` (`breaker_tripped` arg) | open, loud | not disk/memory |
| `dispatch:missing_tools` | `lib/dispatch_concurrency.py:can_start_another` (`missing_tools` arg) | open, loud | not disk/memory |
| `dispatch:task_records` | `lib/dispatch_concurrency.py:_read_task_records` | open, loud | not disk/memory |
| `dispatch:credit_remote` | `lib/dispatch_concurrency.py:credit_ready_remote` | open, loud | not disk/memory |
| `dispatch:local_state` | `lib/task_dispatch.py:_read_local_dispatch_state` | open, loud | not disk/memory |
| `dispatch:remote_state` | `lib/task_dispatch.py:_read_remote_dispatch_state` | open, loud | not disk/memory |
| `tailscale:online_hosts` | `lib/task_dispatch.py:_tailscale_online_hosts` | open, loud | not disk/memory |
| `breaker:record_failure` | `lib/run_ticket.py:_feed_breaker`, `lib/box_build.py` (inline) | open, loud | not disk/memory; catches the "signature mismatch" case from a narrowed except |

A test walks every `guard_reading.reading(` call site in the tree by source grep and asserts the name is a key in `FAIL_MODE` — this is "a guard added later without a table entry: the test fails," taken literally.

## Tests first

1. `lib/tests/test_guard_reading.py` (new):
   - `reading()` returns the value unchanged on a readable call, and `None` on an unreadable one (value is `None`, or an `Exception` instance).
   - First unreadable call opens an episode (`since` set, `streak_unreadable == 1`); a second consecutive unreadable call within the window keeps the same `since` and increments the streak — not a new episode.
   - **Flapping is one episode, not many:** unreadable → readable (once) → unreadable again within a short window must NOT close the episode; only `streak_readable >= 2` (or readable continuously for the clear window) closes it. Covers the ticket's explicit break-it case.
   - 30-minute-without-2-reads case: one unreadable reading, then silence (no more calls) past 30 minutes — a second call after 31 minutes still reads as an ongoing (now older) episode, not a fresh one.
   - Malformed/corrupt state file (truncated JSON, a JSON array instead of an object, file replaced mid-read) never raises; `reading()` degrades to "treat as a fresh episode" and self-heals the file on the next write. (Misuse: malformed input.)
   - Two processes calling `reading()` for different guards at the same instant don't lose either guard's update (concurrency; uses the same `tmp_path` + real `fcntl.flock`, not a mock, since the lock is the actual collaborator here).
   - A guard name that is not in `FAIL_MODE` raises/asserts loudly in the helper itself in debug use, AND the source-grep coverage test (below) catches it even if the module's own unit tests never import it directly.
   - Huge/garbage `value_or_error` (a 10 MB string, a custom exception whose `__str__` itself raises) never crashes `reading()` and the stored detail is bounded.
   - `test_every_guard_call_site_is_in_the_table`: greps `lib/**/*.py` and `dashboard/**/*.js` for `guard_reading.reading(` / the CLI's `reading` subcommand, extracts the literal first argument, asserts every one is a `FAIL_MODE` key. Fails if a future call site is added without a table entry.
   - `alert_degraded()`: a guard unreadable for exactly 2h fires one alert; the same guard still unreadable 10 minutes later (next sweep) does not re-fire that day; once readable again it fires one "cleared" alert. (Reuses `mr_notification.alert_on_change`'s own already-tested dedup — this test is about wiring the `bad=` tuple and item shape correctly, via `fire=` injection, not re-testing `alert_on_change` itself.)

2. `lib/tests/test_memory_guard.py` (extend): `check()` with `read_level` returning `None` now refuses (closed), with a message distinct from the warn/critical message (says "can't read memory pressure", not "pressure: warn"); refusing on unreadable still never kills anything running (unchanged invariant) and still queues `argv` the same way warn/critical does.

3. `lib/tests/test_disk_trim.py` or new `test_disk_triggers.py` (extend): `preflight()` with `free()` returning `None` now refuses (closed) rather than passing; `reclaim()` still attempted first before the refusal, same as the low-but-readable path, so a transient unreadable statvfs that clears after one `reclaim()` retry still lets work through. Real collaborator: call `preflight` with a `free` callable that genuinely raises (not a mock return value) to match how `os.statvfs` actually fails on a missing/permission-denied path.

4. `lib/tests/test_ticket_pipeline.py` (extend):
   - `_free_disk_gb_remote(host)` (new): a real `ssh` to a bogus host times out/fails → `None`, recorded via `guard_reading.reading("disk:dispatch_remote", ...)`; mirrors `dispatch_concurrency.credit_ready_remote`'s own test (same injected `run`).
   - `_select_for_profile` with the remote probe returning `None` now refuses dispatch to that remote machine (closed), where today it silently proceeds.

5. `lib/tests/test_task_dispatch.py` (extend, must not break the 6 existing `_read_remote_dispatch_state` hook-error-log assertions at lines ~200–268):
   - `_tailscale_online_hosts()`'s existing-behavior test (`== set()` on CLI failure, line 110) still holds, PLUS a new assertion that a `guard_reading` reading was recorded for `tailscale:online_hosts`.
   - `_read_remote_dispatch_state` and `_read_local_dispatch_state` on failure: existing `_log_hook_error_safe` calls still fire (regression guard) AND a `guard_reading` reading is recorded; a CLI genuinely missing from `PATH` (launchd's actual failure mode per #889) is simulated the way the module already does elsewhere (an absolute-but-wrong binary path), not just a monkeypatched exception.

6. `lib/tests/test_dispatch_concurrency.py` (extend): `_read_task_records` on one malformed `*.json` file among several valid ones: the valid ones still count (unchanged), and the malformed one now shows up via `guard_reading.reading("dispatch:task_records", ...)` instead of vanishing with no trace.

7. `lib/tests/test_run_ticket.py` / `lib/tests/test_box_build.py` (extend): `_feed_breaker` / box_build's inline `record_failure` call narrowed to catch only the environmental exceptions it's meant to (`OSError`); a `TypeError` from a bad call signature is now recorded via `guard_reading.reading("breaker:record_failure", exc)` rather than silently vanishing — and the run still settles normally (never raises up to the caller, unchanged invariant). Must not break any of the ~12 existing `record_failure` monkeypatch tests already listed in this file.

8. `lib/tests/test_health_checks.py` (extend): new `check_guard_readings()` — no guards unreadable → `[]`; one guard unreadable for 1 reading/5 minutes → no row yet (below both thresholds); one guard unreadable for 2 readings, or for 31 minutes on one reading → one yellow row, never green, naming the guard and duration; multiple guards unreadable → multiple rows, each independent (one guard's episode must not mask or merge with another's — same spirit as `evaluate_repo_sync`'s per-condition findings).

9. `dashboard/test/merge.test.js` (extend): `rebaseAndRetest` with `freeBytes` rejecting (today: `.catch(() => null)` then "carry on") now returns `{ok: false}` with a `GATE_INFRA`-shaped reason instead of proceeding; the first-aid path is still attempted first when `free` later becomes unreadable mid-run, matching the existing retry-once-then-refuse shape already in the file.

10. Misuse not explicitly in the ticket's list but required by the north stars' "tests try to break it": a guard-state file owned by root / 0400 permissions (wrong permissions) is read-only to `reading()`'s writer — never raises, degrades to "couldn't persist this reading" (logged once via the existing `error_log`/hook-error path, not a crash); a stale state file from a different, long-dead episode (process crashed mid-episode weeks ago) is correctly treated as old on the next real reading, not as "still ongoing since then" forever (bounded episode age, so a crash doesn't manufacture a permanent yellow row).

## Decisions

None needed. Gil already decided `guard-unreadable` on the issue and in the design doc ("Per guard: closed for disk and memory ... open but loud for the rest"); nothing else here requires his input. One implementation judgment call I made myself rather than asking: episodes clear using the same 2-reading/30-minute hysteresis on the way *down* as on the way up (symmetric), to satisfy the ticket's explicit "flapping is one episode, not many" break-it case without inventing a second set of constants.

## Task List

1. **`lib/guard_reading.py` (new):** `FAIL_MODE` table (13 entries above); `STATE_PATH = ~/.claude/logs/guard-state.json`; `reading(name, value_or_error, *, now=None, detail=None)` — fcntl-locked read-modify-write of the state object, symmetric 2-reading/30-min hysteresis for opening and closing an episode, bounded/truncated detail text, self-heals a corrupt state file; `alert_degraded(state=None, path=..., fire=None, today=None)` wrapping `mr_notification.alert_on_change(bad=("degraded",))`; a tiny CLI (`guard_reading.py reading NAME --ok|--error TEXT`) for the merge gate's JS caller.
2. Write `test_guard_reading.py` per the tests-first list (including the source-grep coverage test) before any call site changes.
3. `lib/memory_guard.py:check` — fail closed on `level is None`, with its own message; route both outcomes through `guard_reading.reading("memory:pressure", ...)`.
4. `lib/disk_triggers.py:preflight` — fail closed when `free()` is `None` even after `reclaim()`; route through `guard_reading.reading("disk:preflight", ...)`.
5. `lib/ticket_pipeline.py` — add `_free_disk_gb_remote(host)` (ssh, following `dispatch_concurrency.credit_ready_remote`'s shape); wire it into `_select_for_profile`'s `disk_free_gb` lambda for non-self machines; both local and remote reads go through `guard_reading.reading("disk:dispatch_local"/"disk:dispatch_remote", ...)` and now fail the guard closed on `None` (today `None` is silently skipped).
6. `lib/dispatch_concurrency.py` — give `_safe` a `name` parameter so `can_start_another`'s four calls (`disk_free_gb`, `github_budget_pct`, `breaker_tripped`, `missing_tools`) each report through `guard_reading.reading(...)` with their own name, staying open/loud; `_read_task_records` reports a per-file parse failure through `guard_reading.reading("dispatch:task_records", ...)` before skipping it (behavior unchanged, now visible); `credit_ready_remote` reports through `guard_reading.reading("dispatch:credit_remote", ...)`.
7. `lib/task_dispatch.py` — `_tailscale_online_hosts`, `_read_local_dispatch_state`, `_read_remote_dispatch_state` each add a `guard_reading.reading(...)` call alongside their existing `_log_hook_error_safe` calls (kept, not replaced); behavior (fail open, local-only / `{"busy": False}`) is unchanged, now counted.
8. `lib/run_ticket.py:_feed_breaker` and `lib/box_build.py`'s inline `record_failure` call — narrow the `except Exception` to `except OSError`, and add an `except Exception as exc: guard_reading.reading("breaker:record_failure", exc)` branch so a signature mismatch is loud instead of swallowed; still never raises to the caller.
9. `dashboard/webhook-server/merge.js:rebaseAndRetest` — on `freeBytes` rejecting, shell out to `guard_reading.py reading disk:merge_gate --error ...` (best effort, never throws) and change the `free === null` branch from "carry on" to refuse closed with a `GATE_INFRA`-shaped reason; on a successful read, report `--ok`.
10. `lib/health_checks.py` — add `check_guard_readings()` (reads `guard-state.json`, returns one yellow row per open episode meeting the 2-reading/30-min threshold, severity never green), register it in `write_status()`'s check list; add `react_to_guard_readings()` (calls `guard_reading.alert_degraded()`) and wire it into `_cli()` alongside `react_to_accounts()`.
11. Run the full Python suite (`lib/tests`) and the dashboard JS suite locally before opening the PR, given this ticket's history of test-slot timeouts and a prior "code review found must-fix issues" send-back — keep new tests fast/unit (no new full-suite-triggering paths) per `main_health.py`'s own documented cost concerns.
12. Update `instance/docs/plans/failure-containment-2026-10-30.md`'s "Quick wins built now" section to record this as built, and close out the `guard-unreadable` row's listed gaps (#889, #891 baselines) against the recurrence check due 2026-11-20.