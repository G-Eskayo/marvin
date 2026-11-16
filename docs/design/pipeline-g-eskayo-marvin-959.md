All test files exist as expected. I have enough to write the plan.

## North-star fit

**Reuses before adding anything new:**
- `lib/notify.py`'s `notify()` — the one alert path (ADR 0083/`mr_notification._fire`) — for the 2-hour degraded alert. No new notification channel.
- `lib/health_checks.py`'s check-registry pattern: a `check_X()` function returning `_result(id, label, severity, detail, value)` dicts, fed into the sweep's check list (the same shape as `memory_pressure()`, `disk_activity()`, the `<check>@<device>` id convention already used for `disk:space@<device>`).
- The existing "stuck episode" hysteresis already live for code sync (ADR 0077, 30-minute threshold, one notify on entry, debounced recovery) — same shape as what this ticket asks for, reused as the escalation model rather than invented fresh.
- `dispatch_concurrency.save()`'s atomic-write pattern (tempfile + `os.replace`) for the new guard-state file.
- `cold_store.py`'s `Store.listing()` ssh pattern (`df -Pk ~ | tail -1` over the existing `SSH_OPTS`) to give `ticket_pipeline._free_disk_gb` a real remote reading instead of the hardcoded `None` it returns today.

**Simplest sufficient approach:** one small new module, `lib/guard_reading.py`, with a name→fail-mode table and a single wrapper function that every guard call site uses in place of its own ad hoc `except: return None/default` (there are at least 9 such idioms today across `dispatch_concurrency._safe`, `task_dispatch`'s bare excepts, `memory_guard`/`disk_triggers`'s `except: return None`, and `failure_breaker._read`'s skip-corrupt-line). Same value-or-`None` contract as today at each call site, so most callers change by one line; only the two guards the owner decided should fail closed (disk, memory) change actual behavior.

**Tokens/compute:** pure local file I/O (one small JSON state file, one extra Health-sweep check); no LLM calls added. Spends a little code-complexity budget (one new module, ~9 call sites touched) to close two multi-day blind spots (#889: 4 days, #891: since parallel slots shipped) that cost far more in undetected downtime than this costs to build.

**Phone-OS / capability:** directly serves north star 2 ("nothing may break silently") — a precondition for anything proactive or reliable. Gil goes from discovering these failures days later by symptom to seeing them on Health within 30 minutes/2 reads and getting paged at 2 hours; it's the system doing a check nobody was doing, not new manual work for him.

**Machine:** lives in `lib/`, runs wherever the guard already runs (Mini, laptop, or a guard reading a remote peer over ssh) — no new single-machine dependency.

The ticket's own "North star: 2" citation is correct; no correction needed.

---

## Guard inventory and fail mode (owner's decision already made: disk/memory closed, everything else open+loud)

| Guard name | Call site | Today's silent behavior | New mode |
|---|---|---|---|
| `disk` (local) | `dispatch_concurrency.can_start_another`'s `_safe(disk_free_gb, machine)` | unreadable → pass | **closed**: refuse that machine, with reason |
| `disk` (remote) | `ticket_pipeline.py:851` `_free_disk_gb() if s else None` | always `None` for remote → always passes | **closed**: real ssh reading (reuse `cold_store`'s `df -Pk ~`), unreadable → refuse |
| `disk` (preflight) | `disk_triggers.preflight` | `free() is None` → `ok: True` | **closed**: `ok: False`, actionable message |
| `memory` | `memory_guard.check()` via `read_level()` | `level=None` → `not in HIGH` → pass | **closed**: unreadable treated as "warn" (wait) |
| `github_budget` | `dispatch_concurrency._safe(github_budget_pct)` | unreadable → pass | open: counted, yellow, alert at 2h |
| `breaker` | `dispatch_concurrency._safe(breaker_tripped)` | unreadable → pass | open |
| `missing_tools` | `dispatch_concurrency._safe(missing_tools, machine)` | unreadable → pass | open |
| `task_records` | `dispatch_concurrency._read_task_records` | malformed file → silently skipped, undercounts slots | open |
| `tailscale` | `task_dispatch._tailscale_online_hosts` | unreadable → `set()` (looks like "all offline") | open |
| `dispatch_state` | `task_dispatch._read_local/remote_dispatch_state` | any error → `{"busy": False}` | open |
| `failure_log` | `failure_breaker._read()` | corrupt line → silently dropped, undercounts signature matches | open |

---

## Design

`lib/guard_reading.py` (new):
- `FAIL_MODE: dict[str, Literal["open", "closed"]]` — the table above, validated at import (unknown value raises, loud not silent).
- `guard_reading(name: str, reader: Callable, *args, device: str | None = None, **kwargs)`: calls `reader(*args, **kwargs)`; on success, records a readable reading and returns the value; on any `Exception` (including `subprocess.TimeoutExpired`), records an unreadable reading (logged once per call to the one error log, `hook_errors`/`error_log`'s existing path) and returns `None`. Call-site contract unchanged.
- State: `~/.claude/logs/guard-unreadable.json`, keyed by `f"{name}@{device or 'local'}"`, atomic write (tempfile + `os.replace`, matching `dispatch_concurrency.save`). Per key: `consecutive_unreadable`, `first_unreadable_at`, `consecutive_readable`, `alerted_at`, `last_error`.
- Yellow threshold: `consecutive_unreadable > 2` OR `now - first_unreadable_at >= 30min` (ticket's own wording).
- Episode close/reset only after `consecutive_readable >= 2` (same constant, not a new magic number) — this is what collapses flapping into one episode instead of a new one per blip.
- Alert: once per episode, when `now - first_unreadable_at >= 2h`, call `notify("MARVIN: guard unreadable", "<name>@<device> has been unreadable for 2h: <last_error>")`; mark `alerted_at` so it never double-fires within the same episode.
- `flagged_guards(now=None) -> list[dict]`: the rows currently at/above the yellow threshold, for Health.

`health_checks.py`: add `check_guard_readings()` returning one `_result("guard:<name>@<device>", label, "yellow", detail)` per flagged guard (severity is always yellow — the row simply doesn't exist once resolved, so it's "yellow, never green"), wired into the sweep's check list alongside the existing per-machine checks.

Closed guards change real behavior, not just Health, at their 3 call sites (disk) + 1 (memory) listed above. Open guards keep returning `None` to their caller exactly as today; `guard_reading` only adds counting/logging on top.

No remaining Decision: the fail-open/closed choice was already answered by Gil (2026-10-30, "Per guard"); nothing else in this design needs a button.

---

## Tests to write first

1. Reader raises a generic `Exception` (not just `OSError`) → counted as unreadable (today's `_safe`/bare-excepts only catch narrow types in places).
2. Reader raises `subprocess.TimeoutExpired` (a hung probe) → counted like any other exception; `guard_reading` adds no blocking wait of its own.
3. Missing/unreadable/malformed `guard-unreadable.json` → treated as empty state, never raises (same tolerant-JSON idiom used everywhere else in this codebase).
4. **#889 regression**: `TAILSCALE_BIN` pointing at a nonexistent path → `tailscale` guard shows yellow at 30min/2 reads, one `notify()` at 2h, not "every peer offline" with no signal.
5. **#891-shape regression**: a malformed task-record file → `task_records` guard counts it (doesn't just vanish from the slot count silently).
6. Flapping (unreadable → readable → unreadable → readable, each once) → one episode, `first_unreadable_at` doesn't reset on a single readable read, no duplicate alert.
7. A guard call site added without a `FAIL_MODE` entry → completeness test fails (regex-scan `lib/*.py` for `guard_reading("...",` literals, diff against `FAIL_MODE` keys both ways).
8. Remote Mac unreachable over ssh → `ticket_pipeline._free_disk_gb(remote)` reads unreadable (ssh fails/times out), `can_start_another` refuses with a reason — not the current hardcoded pass.
9. Concurrent writers to the state file (health sweep + a live dispatch check at once) → atomic replace means no interleaved/corrupt write; a reader hitting a half-written file degrades to "empty state", never crashes.
10. State file owned/unreadable (wrong permissions) → `OSError` caught, treated as empty state.
11. Stale state from a guard that stopped being polled entirely (not the same as "unreadable") → documented as a known, accepted gap (that's cron_health/coverage's job, not this ticket's); test that `flagged_guards()` only reports guards that were actually probed in-window, so ancient leftover state doesn't fire a phantom 2h alert.
12. Bad `FAIL_MODE` edit (value not `"open"`/`"closed"`) → raises at import/load time.
13. Malformed call: empty/`None` guard name, or `reader` not callable → raises `TypeError`/`ValueError` immediately (programmer error, never silently no-ops).
14. Memory closed-fail: `read_level()` unreadable → `memory_guard.check()` now makes real work wait (like "warn"), not just logs it.
15. Disk closed-fail (preflight): `free()` unreadable → `disk_triggers.preflight` now refuses with an actionable message, not `ok: True`.
16. `notify()` itself failing/erroring when the 2h alert fires → `guard_reading`'s alert step doesn't raise or break the calling guard (`notify()` already never raises; test the dict-error path is handled).
17. **Literal AC**: guard unreadable for ≥2h (faked clock) → exactly one `notify()` call naming the guard, no second one on the next poll within the same episode.

---

## Task List

1. Add `lib/guard_reading.py`: `FAIL_MODE` table, `guard_reading()`, atomic state read/write, episode/threshold/debounce logic, `flagged_guards()`, 2h-alert call into `lib/notify.notify()`.
2. `lib/tests/test_guard_reading.py` covering tests 1–3, 6, 9, 10, 12, 13, 16, 17 above.
3. Wire `disk` (closed) at its 3 call sites: `dispatch_concurrency.can_start_another` (replace `_safe(disk_free_gb, machine)`), `ticket_pipeline._free_disk_gb` (add a real remote ssh reader reusing `cold_store`'s `df -Pk ~ | tail -1` pattern instead of the hardcoded `None`), `disk_triggers.preflight`. Update `test_dispatch_concurrency.py`, `test_ticket_pipeline.py`, `test_disk_triggers.py` for fail-closed behavior (tests 8, 15).
4. Wire `memory` (closed) in `memory_guard.check()`/`read_level()`. Update `test_memory_guard.py` (test 14).
5. Wire the 7 open guards (`github_budget`, `breaker`, `missing_tools`, `task_records`, `tailscale`, `dispatch_state`, `failure_log`) through `guard_reading`, removing `dispatch_concurrency._safe` once nothing calls it. Update `test_dispatch_concurrency.py`, `test_task_dispatch.py`, `test_failure_breaker.py` (tests 4, 5).
6. `health_checks.py`: add `check_guard_readings()`, one `guard:<name>@<device>` row per flagged guard, wired into the sweep. Extend `test_health_checks.py`.
7. Completeness test (test 7) — can live in `test_guard_reading.py`.
8. Run the full touched-module test set locally (`guard_reading`, `dispatch_concurrency`, `ticket_pipeline`, `memory_guard`, `disk_triggers`, `task_dispatch`, `failure_breaker`, `health_checks`) before marking ready, per the full-suite-before-hand-merge rule.