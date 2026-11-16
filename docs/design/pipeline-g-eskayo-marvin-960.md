## North-star fit

**Reuses before adding anything new:**
- `lib/task_dispatch.py:_read_remote_dispatch_state` — extended in place to also parse one `df` line from the *same* ssh call it already makes for the busy check, instead of adding a second round-trip or a new polling path.
- `lib/disk_triggers.py:preflight`/`reclaim`/`record` — called as-is from `run_ticket.run`; no new disk-cleanup logic or logging mechanism.
- `lib/failure_breaker.py:signature` — extended with one more branch (`disk-full`), reusing the existing classifier instead of inventing a second one in `run_ticket.py`.
- `lib/run_ticket.py`'s existing `env_missing` outcome-flag pattern in `build()`/`settle()` — mirrored for the new `disk_full` flag (same "machine fault, not a ticket fault" shape).
- `lib/dispatch_concurrency.py:can_start_another`'s existing `disk_free_gb` guard — untouched; it already does the right thing once it receives a real remote reading instead of a hardcoded `None`.
- Test isolation: conftest.py's existing `_isolate_*`/`_no_real_*` autouse-fixture convention, extended for the two new pieces of state this ticket introduces (a per-process remote-state cache, and `run_ticket`'s new real-disk preflight call).

**Why this is the simplest sufficient approach:** the dispatch-time guard (`can_start_another`) already contains all the logic for "stop sending work to a low-disk machine" — it was just being fed `None` for every remote machine. Fixing the one lambda in `ticket_pipeline._select_for_profile` (plus the remote read it depends on) makes that guard correct for both machines with no new state or polling loop; it's a *live* check, so "resumes by itself when space is freed" falls out for free. The `run_ticket.run` preflight and the `failure_breaker.signature` fix are the two narrow additions the live guard can't cover (non-parallel mode, and the race between dispatch-time and build-time).

**Where it spends/saves tokens or resources:** one extra `df` appended to an ssh call that already happens, cached for the life of the scan process so N tickets/profiles in one scan never re-ask the same host twice (saves ssh round-trips, north star 1). `run_ticket.run`'s new preflight is one local `statvfs` call before any model/build work starts — avoids spending a full build attempt (and a Claude call) on a machine that's already known to be unable to finish it.

**North star 5** is the direct target: a disk-starved machine stops taking work automatically and rejoins automatically, with no manual intervention and no other machine's capacity wasted compensating for it.

**Leaves the user more capable:** Gil stops having to notice "the Mini is at 1.6 GB, why do two tickets keep getting wrongly parked" and intervene by hand; MARVIN now self-diagnoses and self-heals this specific failure mode, matching the `code_trip`/circuit-breaker self-healing pattern already established for stale code.

No recorded CONTEXT.md/ADR decision contradicts this design (checked the "Disk triggers", ADR 0052 parallel-dispatch, and "#881 every outcome feeds the breaker" passages).

## Decisions
None needed — the ticket names exact files, functions, and line numbers, and no genuine either-way judgment call surfaced during design. (I treated "record disk-full against the machine" as meaning *both* the preflight-caught and mid-build cases feed `failure_breaker` with a correctly-labeled `disk-full` reason, since bullet 3's signature fix is otherwise dead code — this is the literal reading of the ticket, not a coin-flip, so I did not raise it as a Decision.)

## Tests written first

**Remote disk check (`task_dispatch.py`, `ticket_pipeline.py`):**
1. `_read_remote_dispatch_state` parses a combined `cat`+`df` ssh reply into `{"busy": ..., "disk_free_gb": ...}`.
2. Calling it twice for the *same* host in one process makes exactly one `subprocess.run` call; a different host makes a second call (cached-for-the-scan).
3. ssh non-zero exit / subprocess exception / malformed or empty `df` line → `disk_free_gb` is `None`, never `0` or a bogus number ("unreadable, not fine").
4. All six existing busy-check tests (non-zero, empty stdout, JSON-decode failure, subprocess exception, success, stderr truncation) still pass unmodified.
5. `_select_for_profile` (parallel on): a remote machine with a real `tailscale_hostname` whose `remote_disk_free_gb` is mocked low is refused with a `"disk X GB free on <machine>"` reason; self with healthy disk is still chosen.
6. `tp.main()` end-to-end (extends `_parallel()`): remote low, self healthy → only self's project gets dispatched; the other project's ticket stays unclaimed.
7. Both machines low → `tp._scan()` claims nothing, tickets stay unclaimed, and the refusal is reported in the scan's step/summary log (extends `test_a_guard_refusal_starts_nothing_and_says_why_in_the_scan_log`).
8. Unreadable remote disk never blocks dispatch to that machine (the `None`-never-blocks contract, now exercised with a real remote reader instead of the hardcoded `None`).
9. Two different machines in the same scan, one low/one fine, are never conflated (cache keyed per host).

**`run_ticket.py` preflight + `disk_full` outcome:**
10. `run()` calls `disk_triggers.preflight(...)` before `build()`; `ok: True` → `build()` runs exactly as before (regression safety).
11. `ok: False` → `build()` is never called; claim released with no comment and no park even at a high failure streak; stage recorded "done/failed"; redispatch triggered; `outcome["disk_full"] is True`.
12. Mid-build: `execute_ticket` raises `OSError(28, "No space left on device")` → `outcome["disk_full"] is True`; claim released without a park/comment at a high streak, but `failure_breaker.record_failure` **is** called (so 3 distinct tickets still trip the cross-ticket breaker, now correctly labeled).
13. `_outcome_kinds()` gets a `"disk_full"` entry; the existing walk test (`test_every_non_success_outcome_feeds_the_breaker_unless_it_is_a_named_exception`) enforces it's fed to the breaker since it's deliberately not in `BREAKER_EXEMPT`.
14. `test_the_exemptions_are_named_with_a_reason_and_only_env_missing` stays unchanged — pins that `disk_full` was *not* added to `BREAKER_EXEMPT`.

**`failure_breaker.signature`:**
15. `"...No space left on device..."` → `"disk-full"`.
16. `"[Errno 28] ENOSPC"` and case-variants → `"disk-full"`.
17. A message that mentions "disk" without either literal phrase still falls through to `other:...` (negative case — the match stays specific).

**New test isolation (conftest.py), both following the file's existing pattern:**
18. Autouse fixture resetting `task_dispatch._remote_state_cache` between tests (otherwise the new cache leaks mocked results across the existing `_read_remote_dispatch_state` tests).
19. Autouse fixture defaulting `run_ticket.disk_triggers.preflight` to `{"ok": True, ...}` so the ~30 existing `rt.run(...)` tests never touch this machine's real free disk space (mirrors `_no_real_disk_housekeeping`/`_no_du_on_the_real_home`).

## Task List

1. **`lib/task_dispatch.py`**: add module-level `_remote_state_cache` dict; extend `_read_remote_dispatch_state` to run `cat <state> ; echo <marker> ; df -Pk "$HOME" | tail -1` in the one existing ssh call, parse the `df` line into `disk_free_gb`, merge it into the returned dict, and cache the result per host. Add `remote_disk_free_gb(host) -> float | None` accessor. Add `_parse_remote_disk_gb(line) -> float | None` helper.
2. **`lib/ticket_pipeline.py`**: change `_select_for_profile`'s `disk_free_gb` lambda to call `task_dispatch.remote_disk_free_gb(info.get("tailscale_hostname"))` for non-self machines instead of hardcoding `None`; update the surrounding comment (lines ~824-830) that currently says remote machines are only "trusted."
3. **`lib/failure_breaker.py`**: add a `signature()` branch matching `"no space left on device"` / `"enospc"` (case-insensitive) → `"disk-full"`, placed before the generic fallback.
4. **`lib/run_ticket.py`**: import `disk_triggers`; in `run()`, call `disk_triggers.preflight(f"ticket {repo}#{issue_number}")` before `build()`; on failure, build an outcome with `reason` phrased to include "no space left on device" (so `failure_breaker.signature` classifies it) and `disk_full=True`, and route straight to `settle()` without calling `build()`. In `build()`'s generic `except Exception` handler, set `outcome["disk_full"] = True` when `failure_breaker.signature(reason) == "disk-full"`. In `settle()`, add one branch for `outcome.get("disk_full")`: release the claim, feed `failure_breaker`, record the stage, trigger redispatch, return — no comment, no park.
5. **`lib/tests/conftest.py`**: add the two new autouse isolation fixtures (remote-state cache reset; default `run_ticket.disk_triggers.preflight` to pass).
6. **`lib/tests/test_task_dispatch.py`**: tests 1–4, 8–9 above.
7. **`lib/tests/test_ticket_pipeline.py`**: tests 5–7 above (extend `_parallel()`/`_capture()` fixtures to wire `tailscale_hostname` and patch `remote_disk_free_gb`).
8. **`lib/tests/test_run_ticket.py`**: tests 10–14 above.
9. **`lib/tests/test_failure_breaker.py`**: tests 15–17 above.
10. Short addition to `CONTEXT.md`'s existing "Disk triggers" passage (marvin#765 area) noting the remote-disk fix, the `run_ticket.run` preflight, and the `disk-full` signature, so the next reader of that passage sees the full picture in one place.