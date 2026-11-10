## North-star fit

**Reuses, before adding anything new:**
- `lib/webhook_restart.py`'s existing `decide()`/`_facts()`/`main()` pure-function pattern (already modeled on `lib/dashboard_rebuild.py`) — this script already restarts `com.marvin.dashboard-webhook` when its code is stale, already runs every 30 min from `com.marvin.code-sync-push.plist` step 6. It just never checks `merge-inflight.json`, and nothing fires it sooner than the 30-minute cycle.
- The **merge-ending trigger** already named and used in `dashboard/webhook-server/merge.js`: `withMergeMark()`'s `finally` block calls `kickMemoryGuard()` on every merge's end (success or failure), reached through the one real merge entrypoint (`runMerge` in `index.js`, used by both direct Approve and `merge_queue.js`'s `drain()`). `merge_queue.js`'s own comment already calls this "a merge ending" as a named trigger class, alongside "an Approve" and "the webhook's GitHub change pings."
- `code_sync.py pull`, the one blessed way code reaches a clone — already invoked the same way, for the same race (`gh pr merge` lands on GitHub before the local clone has it), in `dashboard/scripts/rebuild_and_install.sh` (comment cites PR #317, the exact prior incident). It already has a per-clone `flock` run-lock (#1188/#1189, merged just before this ticket) and the conflict-marker guard (ADR 0022), so concurrent/failing pulls are already safe — I'm not rebuilding any of that.
- The existing `webhook:build` Health card (`lib/health_checks.py::evaluate_machine_state`, feeding `check_machine_state_everywhere`) already turns yellow/red when the webhook-server's start time is older than origin/main's latest commit touching `dashboard/webhook-server`/`dashboard/electron/main`. This already satisfies AC2's amber requirement; it only needs to additionally *show the version*, not learn to detect staleness.
- `merge_progress.js`'s `createInflightStore`/`inflightPath()` (`~/.claude/logs/merge-inflight.json`) — read, never reinvented, from the Python side.

**Why this is the simplest sufficient approach:** four surgical edits to already-correct machinery (one new fact + one new guard in `decide()`, one new trigger call at one existing hook point, one subprocess call reusing `code_sync.py pull`, one string enrichment in an existing Health check) — no new files, no new service, no new polling loop, no new storage.

**Token/compute cost:** spends a little (a `git log`/`ps`/file-read per merge-ending event, same cost class as the existing `kickMemoryGuard` call); saves a lot — it deletes the recurring manual "diagnose Mini, `code_sync.py pull`, `launchctl kickstart`" fire drill (the 2026-11-02 incident this ticket exists to prevent), and the 3-day blind spot before anyone noticed.

**Phone-OS direction:** neutral — a reliability fix to automation infrastructure, not a surface Gil touches.

**More capable, not more passive:** yes — Gil currently has to notice staleness himself (nothing alerted him for 3 days) and fix it by hand. After this, it fixes itself within about a minute of a merge, and Health tells him plainly when it's behind and why, with no judgment call taken away from him (there is none to take — this is pure mechanical upkeep).

## Decisions
<!-- marvin:decisions -->
### settle: Restart latency for the merge-ending trigger vs. the existing 60s settle window
`webhook_restart.decide()`'s `SETTLE_SECONDS = 60` exists to avoid restarting on a change that might still be mid-push, which matters for the slow 30-minute poll (it's reading arbitrary git state, no guarantee a push is finished). The new merge-ending trigger fires only after `gh pr merge` has already returned successfully — the commit is already 100% final — so that risk doesn't apply there the same way.
- [ ] A: Bypass the settle wait for the merge-ending trigger only (keep it for the 30-min poll). Gets AC1's "within a minute" to a few seconds typically. (Recommended — it's the literal AC.)
- [ ] B: Keep one uniform 60s settle for both triggers (simpler: one code path, no "which caller is this" branching). Typical latency becomes ~60–90s, arguably still "within a minute" in spirit but not literally.

## Tests (written first)

**`lib/tests/test_webhook_restart.py` (extending the existing suite):**
1. `test_skips_when_a_merge_is_in_flight` — `decide(merge_inflight=True, ...)` returns `"skip"` even when every other condition says restart.
2. `test_merge_inflight_blocks_even_when_backoff_window_has_passed` — in-flight check is evaluated independently of/ahead of the backoff timer, so it isn't accidentally bypassed by unrelated timing.
3. `test_restarts_once_merge_is_no_longer_in_flight` — `merge_inflight=False` with an otherwise-stale server still restarts (regression guard once the new param exists).
4. `test_merge_inflight_reads_the_real_file_as_empty_means_no_merge` / `..._nonempty_dict_means_a_merge_is_running` — the new file-reading helper against `{}`  vs `{"<url>": {...}}`.
5. `test_merge_inflight_fails_open_on_missing_file`, `..._on_malformed_json`, `..._on_a_json_value_that_is_not_an_object` (list/number/string) — matches this codebase's fail-open convention (a broken signal can't wedge the merge server forever).
6. `test_pull_runs_before_facts_are_gathered` — mocked `subprocess.run`, assert `code_sync.py pull` is called before the git-log staleness check.
7. `test_pull_failure_skips_without_crashing_and_leaves_the_old_server_running` — mocked pull returns non-zero; `main()` logs why, does not call `launchctl kickstart`, exits 0 (How we'll try to break it #2: "a pull that fails... the old server keeps running").
8. `test_two_triggers_in_quick_succession_only_restart_once` — call `main()` twice back-to-back with a mocked subprocess layer (first call "succeeds" and advances the simulated server-start time); assert `launchctl kickstart` is invoked exactly once across both calls (How we'll try to break it #3).
9. `test_attempt_file_is_written_before_the_kickstart_call` — regression guard on the existing ordering (a crash mid-restart still backs off).
10. `test_decide_handles_no_agents_checkout_or_permission_error_without_crashing` — `_facts()`'s git/ps calls failing (wrong machine, no `~/.agents`, permission denied) still yields a clean `(action, reason)`, no exception (misuse: wrong machine/permissions).
11. `test_pull_uses_the_same_code_sync_entrypoint_rebuild_and_install_uses` — asserts the subprocess argv matches `[<venv python>, .../lib/code_sync.py, "pull", <agents path>]`, so it inherits the run-lock/conflict-marker/union-merge guards rather than a bespoke reimplementation.

**`dashboard/test/merge.test.js` (extending the existing suite):**
12. `withMergeMark` calls the new webhook-restart-check trigger in its `finally`, alongside `kickMemoryGuard`, on a successful merge.
13. ...and also on a merge that throws/fails (mirrors however the existing `kickMemoryGuard`-on-failure case is tested).
14. The trigger is fire-and-forget: a spawn that throws/rejects does not propagate and does not affect the merge's own response (mirrors `triggerDiskCleanup`'s swallow-errors pattern).
15. Two merges ending back-to-back each call the trigger independently (dedup is the Python side's job, not the JS side's) — the JS call itself doesn't throw or skip on rapid repeats.

**`lib/tests/test_health_checks.py` (extending `evaluate_machine_state`/`parse_machine_state` coverage):**
16. When `webhook:build` is amber/red, its detail string includes the short SHA of main's latest relevant commit ("AC3: Health shows the merge server's running code version against main").
17. When current (green), the message is unchanged from today (no SHA noise forced into the green case) — regression guard.
18. A git/network failure while fetching the SHA degrades to today's hours-only message rather than crashing the machine-state check (dependency failing).

## Task List

1. `lib/webhook_restart.py`: add a `merge_inflight(path=...)` helper reading `~/.claude/logs/merge-inflight.json`, fail-open (missing/malformed/non-dict → `False`). Add `merge_inflight: bool` to `decide()`, checked right after the "no commit to compare" guard, returning `("skip", "a merge is in flight; will retry once it ends")` when true. Update `_facts()` to include it. Have `main()` run `code_sync.py pull ~/.agents` (via `sys.executable`, same invocation `rebuild_and_install.sh` uses) before gathering facts, tolerating a non-zero exit (log + proceed to skip, never raise).
2. Apply the Decision from `settle` above: either branch the settle check on a new `immediate: bool` param (Option A) or leave it unconditional (Option B).
3. `dashboard/webhook-server/merge.js`: add a `WEBHOOK_RESTART_SCRIPT` path constant (next to `MEMORY_GUARD_SCRIPT`/`DISK_TRIGGERS_SCRIPT`) and a `triggerWebhookRestartCheck(spawnFn = spawn)` function matching `triggerDiskCleanup`'s shape (detached, `.unref()`, try/catch logs only). Call it from `withMergeMark`'s `finally`, alongside the existing `kick()` call.
4. `lib/health_checks.py`: extend `_MACHINE_STATE_SCRIPT` to also emit the short SHA of origin/main's latest commit touching the webhook paths (one extra `git log -1 --format=%h` alongside the existing `%ct` query, or combine into one call). Extend `parse_machine_state` to carry it, and `evaluate_machine_state`'s `webhook:build` branch to append "(main is now at `<sha>`)" to the amber/red detail only, with a graceful fallback when the SHA can't be read.
5. Run the full Python + dashboard vitest suites locally before raising the PR (per the full-suites-before-hand-merge convention), plus the new tests above.
6. Open the PR against `G-Eskayo/marvin`, carrying the `## Decisions` block above, linked to issue #998 ("Closes #998").