## North-star fit

**Reuses, before adding anything new:**
- The append-only-JSONL-log-of-events pattern already used by `memory_guard.record()` (`lib/memory_guard.py:116`), `disk_triggers.record()` (`lib/disk_triggers.py:70`) and `failure_breaker._append()` (`lib/failure_breaker.py:75`) — `guard_reading`'s log is a fourth instance of the same idiom (one JSON line per event, bounded, never raises), not a new logging mechanism.
- `health_checks._result`/`_unknown` (`lib/health_checks.py:48,58`) for the new check's return shape, and `check_catalog_fresh`'s age-threshold pattern (`lib/health_checks.py:425-439`, `CATALOG_YELLOW_AFTER_HOURS`) as the template for "yellow after N minutes."
- The existing alert path end-to-end: `mr_notification.alert_on_change` (`lib/mr_notification.py:185`) and its thin specialisation `health_checks.alert_red_checks` (`lib/health_checks.py:1965`, wired at `lib/health_checks.py:1987`) already do exactly "alert when it turns bad, remind once a day, alert when it clears" with marker-file dedup. The new `alert_degraded_guards` is a second thin specialisation of the same primitive (`bad=("degraded",)`), not a new alert channel.
- The already-established convention that every one of these guard readers returns `None` on failure rather than raising (`read_level`, `free_bytes`, `_free_disk_gb`, `_github_budget_pct`, `tailscale_online_hosts_or_none`). `guard_reading(name, value_or_error)` is a transparent pass-through logger over that existing convention (`None`, or an exception instance from `_safe`, means unreadable; anything else, including `False`/`0`/empty collections, is a real reading) — most call sites change by exactly one line (`x = read()` → `x = guard_reading("name", read())`).
- `dispatch_concurrency._safe` (`lib/dispatch_concurrency.py:152`) stays the chokepoint inside `can_start_another` where disk/GitHub-budget/breaker/tools are already swallowed; `guard_reading` wraps its *output* at each of those 4 lines rather than restructuring the function.
- `credit_ready_remote` (`lib/dispatch_concurrency.py:266`) and `slots_in_use_remote` (`lib/dispatch_concurrency.py:347`) are the existing template for the one real gap the table exposes — remote disk is never actually asked (`ticket_pipeline.py:851`, hard-coded `None`) — so fixing it means adding `_free_disk_gb_remote(host)` the same SSH shape, not inventing a new remote-read style.

**Why this is the simplest sufficient approach:** one new ~40-line module (`lib/guard_reading.py`: the table, the log, the episode fold) plus one-line wraps at 8 existing read sites, one new Health check function (returns a list of 8 rows, same shape every other multi-row check already uses — e.g. `check_missing_profiles`), and two new thin alert wrappers reusing `alert_on_change`. No new service, no new polling loop, no new log-reading convention, no schema change to `RESULT_TEMPLATE`.

**Tokens:** zero LLM cost anywhere in this path — pure deterministic file I/O and arithmetic, same class as `failure_breaker` ("deterministic and token-free"). Cost is one bounded JSONL read per 15-minute Health sweep, same order as `error_log.recent`.

**Phone-OS direction:** tangential — this is reliability plumbing, not a surface.

**More capable or more passive:** more capable. Today #889-style silences run for days before anyone notices; after this, the same failure shows yellow within 30 minutes and reaches Gil within 2 hours instead of him discovering it by hand days later.

**Machine:** per-Mac, like every sibling log here (`pipeline-failures.jsonl`, `hook-errors.log`, `disk-triggers.jsonl`) — no cross-machine aggregation needed for this ticket; `pipeline:breaker`'s existing SSH-merge pattern is there if a future ticket wants it.

**Decisions:** none new. The owner already decided `guard-unreadable` (per-guard: closed for disk/memory, open-but-loud for the rest) and the issue gives exact thresholds (2 readings/30 min to yellow, 2 h to alert) — nothing left for a Decisions block. One judgment call I'm making unilaterally, not a button: fixing the remote-disk-never-asked gap by adding real SSH reading (mirroring `credit_ready_remote`) rather than leaving it permanently "unreadable," since leaving it permanently unreadable-and-closed would silently kill all remote parallel-slot growth — that's exactly the silent-regression shape north star 2 forbids, and the fix is a direct reuse of an existing pattern, not a new design axis.

## Tests to write FIRST

**`lib/guard_reading.py` (new, unit):**
1. `guard_reading("disk", some_exception)` and `guard_reading("disk", None)` both log unreadable and return `None`; `guard_reading("disk", 42.0)` logs readable and returns `42.0` unchanged (pass-through contract).
2. `guard_reading("not-a-real-guard", True)` raises — a guard without a table entry fails loudly, not silently (the "added later without a table entry" break case).
3. `GUARD_TABLE` has exactly the 8 names (`disk`, `memory`, `task_records`, `peer_state`, `tailscale`, `github_budget`, `breaker`, `tools`) mapped to `"closed"` only for `disk`/`memory`.
4. The log directory missing is created on first write (mirrors `memory_guard.record`); a read-only log directory/file (permission denied) is swallowed — recording must never crash its caller.
5. Malformed lines in the log (truncated JSON, non-dict JSON, binary garbage) are skipped by the episode fold, never raise.
6. A log file far past its size cap is trimmed to the newest half (mirrors `memory_guard`/`disk_triggers`' `LOG_MAX_BYTES`), tested with a burst of writes in one sweep, not just a slow trickle.
7. Onset: 2 consecutive unreadable readings start an episode even if under 30 minutes apart; a single unreadable reading under 30 minutes old does not.
8. Onset: one unreadable reading, 31 minutes pass with no second reading — still an active episode (the 30-minute leg of the OR, independent of the reading-count leg).
9. Flapping: unreadable → readable → unreadable → readable, never 2 good reads in a row — stays ONE continuous episode (`episode_start` never resets); only one alert would ever fire across the whole sequence once it crosses 2 h.
10. Recovery: 2 consecutive good readings clear the episode; the next bad reading afterward starts a genuinely new episode with a new `episode_start`.
11. Alert-boundary: episode age `2h01m` reports as alert-worthy, `1h59m` does not — exact `ALERT_AFTER_HOURS` boundary.
12. A reading timestamped in the future (clock skew) doesn't produce a negative age or crash (reuse `stamped.py`'s future-time convention rather than invent a new one).
13. Concurrent writers (simulated interleaved appends from two callers) each still produce one valid, uncorrupted JSON line (relying on the same unguarded `open(path, "a")` atomicity already trusted by `memory_guard.record`/`disk_triggers.record` — tested explicitly here, not assumed).

**`health_checks.py` additions:**
14. `check_guard_readings()` always returns 8 rows (one per `GUARD_TABLE` name), severity `"yellow"` while an episode is active, `"green"` otherwise, **never `"red"`**, and never `"green"` while an episode is active.
15. `alert_degraded_guards()` fires exactly one `"MARVIN: <guard> input can't be read"` alert the sweep an episode first crosses 2 h (mirrors `test_health_alerts.py`'s existing `alert_red_checks` tests, same `_c()`/`fired`/`tmp_path` style).
16. The same sweep re-run every 15 minutes for 2 days on a guard stuck past 2 h reminds once a day, not every sweep.
17. A guard that clears (2 good reads) and later breaks again gets a second, independent alert — not permanently silenced after its first episode.

**Real call sites (behavioural, "test against the real collaborator"):**
18. `memory_guard.check()`/`guard()` with an injected `level_reader` returning `None` (e.g. `sysctl` missing from launchd's PATH, the real #845-class failure) now returns `ok: False` — a genuine behaviour change from today's silent `ok: True` — and records `guard_reading("memory", None)`; the `"normal"` happy path is unchanged and still records a readable reading.
19. `disk_triggers.preflight()` with an injected `free()` returning `None` (statvfs failure) now returns `ok: False`, distinct from today's `ok: True`; the existing below-floor-but-readable / reclaim-insufficient paths are unchanged (regression guard on what must NOT move).
20. `dispatch_concurrency.can_start_another()`, four sub-cases in one test module: `disk_free_gb` raising now **refuses** (closed — new), while `github_budget_pct`, `breaker_tripped`, and `missing_tools` each raising still **passes** (open — unchanged), and each of the four records its own `guard_reading(name, None)`.
21. `_free_disk_gb_remote(host)` (new): SSH timeout, non-zero exit, and a real numeric reply — each produces the right `float | None`, and feeding that into `can_start_another` now correctly refuses extra remote parallel slots when the remote disk can't be read, closing the "always pass" gap in the table instead of permanently disabling remote growth.
22. `dispatch_concurrency._read_task_records()` with one malformed file among several good ones: the bad file is still skipped and the others still counted (unchanged, lossless), but the call now records exactly one `guard_reading("task_records", None)` — the direct #891 regression test.
23. `task_dispatch.tailscale_online_hosts_or_none()`: CLI missing (`FileNotFoundError`, the exact #889 launchd-PATH failure) still returns `None` (unchanged — open/fail-loud) and now records `guard_reading("tailscale", None)`; the **previously entirely unlogged** non-zero-returncode branch now also records it — closing the actual hole #889 fell through.
24. `task_dispatch._read_remote_dispatch_state(host)`: ssh timeout, non-zero exit, and malformed JSON each still fall back to `{"busy": False}` (unchanged) and each record `guard_reading("peer_state", None)`; a clean read records a readable reading.
25. `ticket_pipeline._github_budget_pct()`: `gh` failing (network down, rate-limited, not on PATH) still returns `None` (unchanged) and records `guard_reading("github_budget", None)`.

**Misuse not explicitly in the ticket's list:**
26. `guard_reading`'s `ok`-determination never mistakes a legitimate falsy value (`0`, `0.0`, `set()`, `False`) for unreadable — only `None`/an exception counts.
27. `episodes()` reads only this Mac's own log file; nothing here implicitly merges another Mac's readings (unlike `pipeline:breaker`'s deliberate cross-machine SSH merge, which is a different, opt-in step).
28. A caller bug that calls `guard_reading` hundreds of times per second doesn't balloon the log within a single sweep window (covered by the size-cap test, exercised as a burst).

## Task List

1. Add `lib/guard_reading.py`: `GUARD_TABLE`, `guard_reading(name, value_or_error)`, the bounded JSONL log + its trimming, and `episodes(now=None)` implementing the 2-reading/30-minute onset and 2-consecutive-good-reads clear rule (tests 1–13).
2. Wire `guard_reading` into `memory_guard.read_level`'s call site in `check()`, and flip the unreadable branch to fail closed (tests 18).
3. Wire `guard_reading` into `disk_triggers.preflight`'s `free()` call, and flip the unreadable branch to fail closed (test 19).
4. Wire `guard_reading` into `dispatch_concurrency.can_start_another`'s four `_safe(...)` outputs (disk, github_budget, breaker, tools); flip only the disk branch to fail closed, leave the other three's pass-through behaviour unchanged (test 20).
5. Add `ticket_pipeline._free_disk_gb_remote(host)` (SSH, mirroring `credit_ready_remote`) and use it in `_select_for_profile`'s remote lambda instead of the hard-coded `None`; route both local and remote readings through `guard_reading("disk", ...)` (test 21).
6. Wire `guard_reading` into `dispatch_concurrency._read_task_records` (log once per call, unreadable if any file was skipped) (test 22).
7. Wire `guard_reading` into `task_dispatch.tailscale_online_hosts_or_none` (all three return paths, including the previously-unlogged non-zero-returncode branch) and into `_read_remote_dispatch_state` / `_read_local_dispatch_state` as `"peer_state"` (tests 23–24).
8. Wire `guard_reading` into `ticket_pipeline._github_budget_pct` (test 25).
9. Add `health_checks.check_guard_readings()` (8 rows, yellow/green only) and register it in `default_checks()`; add `health_checks.alert_degraded_guards()` (reusing `mr_notification.alert_on_change`, `bad=("degraded",)`) and wire it into `_cli()` alongside the existing `alert_red_checks` call (tests 14–17).
10. Run the full guard/dispatch/health test suites (not just the new files) to confirm no regression in the unchanged-behaviour branches (github_budget/breaker/tools/peer_state/tailscale staying open).