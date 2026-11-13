## North-star fit

**Reuses, before adding anything new:**
- `lib/dashboard_rebuild.py`'s `decide()`/`_facts()`/failure-backoff shape (marvin#443) — the exact "compare installed code to origin/main, settle, back off only after a *failed* attempt, never block a legitimate next restart" pattern. `lib/webhook_restart.py` currently predates #443 and still has the blanket "back off 6h after *any* attempt" bug #443 already fixed once for the dashboard app.
- `dashboard/webhook-server/rebuild_check.js`'s `createRebuildCheckTrigger` (debounced spawn, detached so a restart of this very server can't kill the check) — generalized into a shared `createScriptCheckTrigger` factory so the new webhook-restart trigger is a second instantiation, not a new mechanism.
- `dashboard/webhook-server/merge_progress.js`'s existing `~/.claude/logs/merge-inflight.json` (`inflightPath`, `createInflightStore`) — the file the ticket names is already written/cleared at exactly the right moments by `createMergeTracker`. Nothing new to build here, just a Python reader.
- `dashboard/webhook-server/index.js`'s `ping(repo)` handler (already calls `rebuildCheck(repo)` on every GitHub change to `G-Eskayo/marvin`) and `merge_queue.js`'s `afterRun(repo)` (already called after every merge's follow-ups finish) — both already exist as the two trigger points this ticket needs; just add a second call next to each.
- `lib/health_checks.py`'s `evaluate_machine_state` "webhook:build" check (lines ~1289–1301) already compares the running server's start time against `webhook_commit_ts`, which is computed against **origin/main** (line 1055), not local HEAD. **Acceptance criterion 2 ("Health turns amber when the merge server runs code older than main") is already built and tested** (`lib/tests/test_health_checks.py::test_webhook_build_is_yellow_when_a_few_hours_behind_and_red_when_a_day_or_more_behind`). No changes needed there.
- `merge.js`'s `GATE_CLONE_MAX_AGE_MS` (2h) as the reused bound for "how long a real merge can legitimately run," to stop a stray in-flight record from blocking restarts forever.

**Simplest sufficient approach:** the ticket is really "do to `webhook_restart.py` what #443 already did to `dashboard_rebuild.py` (origin/main comparison via instant trigger, non-blanket backoff), plus one new safety gate `dashboard_rebuild.py` never needed" — a live merge, run directly against `~/.agents`'s own working tree for the marvin repo itself (confirmed: `merge.js` falls back to `rebaseAndRetestFn(headRefName, run, REPO_PATH, marvinRunTests, ...)` when `ctx` is null, i.e. for marvin's own PRs), means pulling `~/.agents` mid-merge is not just a restart hazard but a working-tree race. So the merge-inflight check gates **both** the pull and the restart as one unit, exactly matching the ticket's literal wording ("a pull that changes dashboard/webhook-server/ restarts the merge server, but only when... merge-inflight.json is empty").

**Token/compute cost:** no new services, no new file formats, no new IPC — one JSON file already being read in one process is now also read in another. The only new runtime cost is one extra lightweight spawn per real GitHub change (already happening today for `rebuildCheck`).

**Phone-OS direction:** neutral/positive — this is "nothing broken silently" (north star 5/Vitals: "Independence... Flow... Nothing broken silently"), directly the precondition north star.

**User capability:** this is pure reliability plumbing; it removes a 3-day silent staleness failure mode. More capable (trustworthy autonomous merging), not more passive — nothing here replaces a judgment call a person was making.

## Decisions

None needed. Every open question resolves to an existing, already-reviewed pattern in this codebase (listed above); I made the ordinary implementation calls below myself rather than invent a choice:
- Merge-inflight gate blocks **both** pull and restart (not restart alone) — required by the marvin-self-clone finding above, and matches the ticket's literal wording (a global `merge-inflight.json` emptiness check, not a per-repo one).
- A corrupt/unparseable `merge-inflight.json` is treated as empty (no merge running) — this mirrors `merge_progress.js`'s own `readJson(file, {})` fallback for the same file; inventing a different (fail-closed) policy for the same file in a second reader would be an inconsistency, not a safety improvement, since the file is always written atomically by its one owner.
- An in-flight record older than `GATE_CLONE_MAX_AGE_MS` (2h, `merge.js`) is treated as stale and ignored, so a crash that somehow left a stray record (outside the already-handled "webhook restarted mid-merge" case, which clears it at startup via `takeInterruptedMerges`) can't block restarts forever.

## Tests to write first

**From "How we'll try to break it":**
1. `decide()`: a merge in flight (`merge_inflight=True`) when the server is behind → outcome is "wait" (not "restart"), reason names why; once `merge_inflight=False` again, the exact same stale inputs now restart.
2. A pull that fails (git conflict): `code_sync.pull` raising/failing leaves `webhook_server_start_ts` unchanged (old server still running); `health_checks.evaluate_machine_state`'s existing `webhook:build` amber/red already reports why (already-covered by existing tests — add one asserting a failed-pull scenario still surfaces through the existing check, no regression).
3. JS `createScriptCheckTrigger`/new webhook-restart trigger: a burst of pings for one merge spawns the check once, then again after the quiet window (mirrors `rebuild_check.test.js`'s existing "burst of change pings" case) — covers "two pulls in quick succession: one restart" at the trigger layer.
4. Python-side race: two `main()` invocations close together (cron + instant trigger) — a `rebuild_running`-style `pgrep`-based in-progress guard (mirroring `dashboard_rebuild.py`'s `rebuild_running`) means the second is a no-op; also idempotent by construction (`server_start_ts >= webhook_commit_ts` after the first restarts).

**Additional misuse cases the section didn't name:**
5. `merge-inflight.json` missing entirely → treated as empty (safe to restart); present but malformed JSON → also treated as empty (matches `merge_progress.js`'s own fallback).
6. A stale in-flight entry older than `GATE_CLONE_MAX_AGE_MS` → ignored, restart proceeds.
7. Kickstart itself failing (job not loaded / wrong machine) → recorded as a failure, backs off until newer code lands (not a blanket time-based backoff), never crashes `main()`.
8. Repeated identical webhook commit (no new code) → always "skip: current," never restarts twice for the same code.
9. `decide()` always returns a human-readable reason for every branch (existing test pattern, extended to the new "wait" branch).
10. Every existing `test_webhook_restart.py` case continues to pass with the new `merge_inflight` parameter added (default `False` in the test helper `d()`), so no existing behavior silently regresses.

## Task List

1. **`lib/webhook_restart.py`**: add `merge_inflight: bool` to `decide()` — when the would-be action is "restart" and `merge_inflight` is true, return `("wait", "a merge is in flight; restarting now would cut it off")`.
2. Same file: replace the blanket `ATTEMPT_FILE`/`BACKOFF_SECONDS` (6h after *any* attempt) with `dashboard_rebuild.py`'s pattern — a `FAILED_FILE` written only when the `launchctl kickstart` command itself exits non-zero, cleared on success, and `decide()` skips only when `last_failure_ts >= webhook_commit_ts and now - last_failure_ts < RETRY_FAILED_AFTER`.
3. Same file: add `_merge_inflight(now) -> bool` reading `~/.claude/logs/merge-inflight.json` (mirrors `merge_progress.js`'s `inflightPath()`/fallback-to-`{}` semantics), ignoring entries older than `GATE_CLONE_MAX_AGE_MS` (2h, cross-referencing `merge.js`'s constant).
4. Same file: add a `pgrep`-based `restart_running` guard (mirrors `dashboard_rebuild.py`'s `rebuild_running`) so two near-simultaneous invocations don't double-kickstart.
5. Same file: `main()` now always pulls first (`import code_sync; code_sync.pull(HOME / ".agents")`, in-process, no new subprocess) *before* gathering facts, but only when `merge_inflight` is false — when true, it skips the pull too and logs "waiting for merge to end" (no code pulled, no restart attempted).
6. `lib/tests/test_webhook_restart.py`: extend `d()`'s defaults with `merge_inflight=False`; add the new cases from the test list above (1, 5, 6, 7, 8, 9, 10).
7. `dashboard/webhook-server/rebuild_check.js`: extract the existing debounce+spawn body into `createScriptCheckTrigger(scriptArgs, matchRepo, opts)`; keep `createRebuildCheckTrigger`/`REBUILD_CHECK_ARGS` as a thin wrapper so `rebuild_check.test.js` needs zero changes. Add `createWebhookRestartCheckTrigger`/`WEBHOOK_RESTART_CHECK_ARGS` (pointing at `lib/webhook_restart.py`) built on the same factory.
8. New test file `dashboard/test/webhook_restart_check.test.js` mirroring `rebuild_check.test.js`'s four cases for the new trigger (test 3 above, plus the repo filter and spawn-failure-swallowed cases).
9. `dashboard/webhook-server/index.js`: instantiate `webhookRestartCheck = createWebhookRestartCheckTrigger()` next to `rebuildCheck`; call it alongside `rebuildCheck(repo)` inside `ping(repo)`'s existing marvin-change branch; also call it from `afterRun: (repo) => repoJobsDone(repo).then(() => webhookRestartCheck(repo))` in the `createMergeQueue({...})` wiring, so a deferred (merge-in-flight-blocked) restart is retried the moment each merge's own follow-ups finish.
10. Doc touch: update `site/src/content/docs/docs/features/dashboard.mdx`'s "Merge server" row and `site/src/content/docs/docs/features/merge-gate.mdx`'s webhook-server paragraph to describe the instant, merge-safe restart instead of "launchd job, no mention of staleness handling."
11. Run the full Python suite (`lib/tests/`) and the full dashboard suite (vitest) before considering this done, per the full-suites-before-merge rule — this ticket touches shared cron-invoked code (`webhook_restart.py`) and the live merge gate's own webhook process.