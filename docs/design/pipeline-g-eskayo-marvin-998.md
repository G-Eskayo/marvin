## North-star fit

**Reuses, before adding anything:**
- `lib/webhook_restart.py:34` `decide()` — the pure settle/backoff decision that already exists for exactly this restart. It's extended with one more input (`merge_inflight`), not replaced.
- `dashboard/webhook-server/rebuild_check.js`'s `createRebuildCheckTrigger` shape (gate on `repo === MARVIN_REPO`, debounce `minGapMs`, detached spawn, swallow spawn errors) — cloned for a sibling trigger, wired into the exact same already-existing hook point: `index.js:556`'s `ping(repo)` callback inside `startChangeWatch` (the "the webhook already hears the merge" the ticket refers to).
- `dashboard/webhook-server/merge.js:1196` `triggerAfterMerge` — the existing fire-and-forget fan-out that already runs after every merge (`triggerTicketPipeline`, `triggerDiskCleanup`). A third entry is added the same way.
- `lib/health_checks.py:1289-1301`, the `webhook:build` card — **already does item 3 in full**: it reads `origin/main`'s latest commit touching `dashboard/webhook-server`/`dashboard/electron/main` (`_MACHINE_STATE_SCRIPT:1055`) and compares it to the running server's start time, going yellow at 2h behind and red at 24h (`SYNC_YELLOW_AFTER_HOURS`/`SYNC_RED_AFTER_HOURS`). Nothing to build there; stated plainly rather than inventing new Health code.
- `dashboard/webhook-server/merge_progress.js`'s `createInflightStore`/`inflightPath()` — the existing `~/.claude/logs/merge-inflight.json` atomic-write store (temp+rename, so no half-written reads). Read, not duplicated.
- `code_sync.py`'s existing per-clone run lock (`RUN_LOCK_WAIT_S = 60`, #1188) already makes an extra concurrent `pull` safe against the 30-minute cron's own pull.

**Why this is the simplest sufficient approach:** the only real gap is latency and a missing safety check — the pieces that decide *whether* to restart and *that* staleness is visible already exist. The fix is wiring (an earlier trigger point for the existing decision, one more fact it reads) not new machinery. No new store, no new health card, no new schedule.

**Where this saves/spends:** spends a handful of tiny git/JSON reads per GitHub poll tick and per merge (all cheap, already-existing CLI calls); saves the thing that actually cost something here — Gil manually diagnosing and hand-fixing a 3-day-stale merge server. The 30-minute cron stays as an unconditional backstop, so nothing regresses if the new fast path ever misfires.

**More capable, not more passive:** this is pure reliability plumbing behind a system Gil already delegated; it removes a silent-failure class (north star 3's test doesn't really apply — there's no judgment being taken away from Gil here, just a manual `launchctl kickstart` he shouldn't have had to remember).

**Machine:** runs identically on whichever Mac(s) run `com.marvin.dashboard-webhook` (CONTEXT.md still says "both, until #112" even though #112 is closed — stale doc, not this ticket's problem) — the design is per-machine and doesn't care how many run it.

**Ticket's stated fit:** the ticket doesn't state its own north-star fit; the above is original.

## Decisions

None needed. The two judgment calls below have clear engineering answers, not product/UX tradeoffs, so I made them rather than guessing silently:
- **Malformed/unreadable `merge-inflight.json` fails closed** (treated as "a merge is in flight," restart skipped) — the asymmetry of harm favors a delayed restart (caught by the 30-min cron) over a false "no merge running" that cuts one off. A missing file (never created yet) is the normal first-run case and fails open (no merge).
- **The new `triggerAfterMerge` entry and the merge-inflight check fire unconditionally for any repo's merge / any "not running" case** — matching `triggerTicketPipeline`'s existing "every merge, not just the one that touched the relevant files" precedent, since `webhook_restart.py`'s own `decide()` already no-ops safely when there's nothing to do.

## Tests (written first)

**`lib/tests/test_webhook_restart.py`** (extends the existing pure-`decide()` suite):
1. A merge in flight when the pull lands: `decide(merge_inflight=True, ...)` with otherwise-restart-due params → `"skip"`, reason mentions the merge / cutting it off.
2. Merge in flight but the server is already current → still `"skip: server is current"` (inflight doesn't override a message that's already correct).
3. Merge in flight but the server isn't running at all (`server_start_ts=None`) → still `"restart"` — a crashed server has nothing live to cut off; inflight must not block recovery.
4. Two pulls in quick succession, same new commit: first call returns `"restart"` and (via `main()`) writes `ATTEMPT_FILE`; a second `decide()` with that `last_attempt_ts` → `"skip"` (backoff) — this already exists (`test_backs_off_after_a_recent_attempt...`); add a variant combined with `merge_inflight=False` to pin the interaction doesn't regress.
5. `_merge_inflight()`: file never created → `False`.
6. `_merge_inflight()`: file contains `{}` → `False`.
7. `_merge_inflight()`: file contains `{"<pr-url>": {...}}` → `True`.
8. `_merge_inflight()`: malformed JSON (`'{not json'`) → `True` (fail closed).
9. `_merge_inflight()`: valid JSON but not an object (e.g. `[]` or `"x"`) → `True` (fail closed, unexpected shape).
10. `_merge_inflight()`: file exists but unreadable for a non-missing reason (e.g. a directory at that path, or a decode error from binary garbage) → `True` (fail closed), not an unhandled exception.
11. Every decision still carries a human-readable reason (extend the existing `test_every_decision_carries_a_human_readable_reason` to include a `merge_inflight=True` case).

**`dashboard/test/code_sync_check.test.js`** (new, mirroring `rebuild_check.test.js`'s shape exactly):
12. A change on `G-Eskayo/marvin` runs `code_sync.py pull ~/.agents`, and on success spawns `webhook_restart.py` detached with `unref()` called.
13. Changes on other repos never touch it (`trigger(repo)` returns `false`, `exec`/`spawn` never called).
14. A burst of pings (several GitHub events for one merge) runs the pull once, then again after the quiet period (same `minGapMs` debounce test as `rebuild_check.test.js`).
15. A pull that fails (rejects — simulating a conflict/lock): `webhook_restart.py` is never spawned, and the trigger function doesn't throw — "the old server keeps running," nothing escalates here (Health's existing repo-sync card already says why the pull failed).
16. A pull that throws synchronously (spawn/exec error, e.g. `ENOENT`) is swallowed: the watch loop never sees an exception.
17. `exec` is called with the venv Python and `code_sync.py`'s absolute path, args exactly `['pull', '<home>/.agents']`.

**`dashboard/test/merge.test.js`** (extends the existing `triggerAfterMerge` describe block):
18. `triggerAfterMerge` now also spawns `webhook_restart.py` (detached, unref'd) alongside the pipeline scan and disk cleanup.
19. One of the three (ticket pipeline / disk cleanup / webhook-restart-check) throwing on spawn never stops the other two (extends the existing "one failing to start never stops the other" test to 3-way).
20. Calling the trigger twice in a row (two merges finishing back-to-back) doesn't throw; `spawn` is called once per `triggerAfterMerge` invocation (de-duplication of the *actual restart* is `decide()`'s/`ATTEMPT_FILE`'s job, already covered above — this just proves the JS side never crashes on repeats).

Everything here targets the real collaborators already in the repo (`code_sync.py`'s real lock, the real inflight JSON shape, the real `decide()` module) rather than mocks that could hide their rules; only the actual `spawn`/`exec` child-process calls are faked, matching the existing style in `merge.test.js` and `rebuild_check.test.js`.

## Task List

1. `lib/webhook_restart.py`: add `INFLIGHT_FILE` constant and `_merge_inflight()` (fail-open on missing file, fail-closed on any other read/parse problem or non-dict shape).
2. `lib/webhook_restart.py`: add `merge_inflight: bool = False` to `decide()`, gating only the final "behind → restart" branch (not the "not running → restart" branch); update `_facts()` to include `merge_inflight=_merge_inflight()`.
3. `lib/tests/test_webhook_restart.py`: add tests 1–3, 5–11 above (run red, then green against steps 1–2).
4. New file `dashboard/webhook-server/code_sync_check.js`: `createCodeSyncCheckTrigger()` — gate on `MARVIN_REPO`, debounce via `minGapMs` (default 60_000, matching `SETTLE_SECONDS`), `await exec(code_sync.py pull ~/.agents)`, then on success `spawn(webhook_restart.py)` detached + `unref()`; swallow and log any failure at either step.
5. New file `dashboard/test/code_sync_check.test.js`: tests 12–17 above (run red, then green against step 4).
6. `dashboard/webhook-server/index.js`: instantiate `createCodeSyncCheckTrigger()` next to the existing `rebuildCheck`, call it inside the `ping(repo)` callback (`index.js:548-559`) alongside `rebuildCheck(repo)`.
7. `dashboard/webhook-server/merge.js`: add `WEBHOOK_RESTART_SCRIPT` constant, add `triggerWebhookRestartCheck(spawnFn)` (same shape as `triggerDiskCleanup`), add it to `triggerAfterMerge`'s loop array.
8. `dashboard/test/merge.test.js`: extend the `triggerAfterMerge` describe block with tests 18–20 above (run red, then green against step 7).
9. Run the full Python suite (`pytest lib/tests/`) and the full dashboard suite (vitest) — not just the touched files — before considering this done (per the "full suites before a hand-merge" rule), since both `webhook_restart.py` and `merge.js` are shared, widely-imported modules.
10. Manually verify on the Mini (or note as a follow-up if not reachable from this worktree): touch a `dashboard/webhook-server/` file, merge it, and confirm via `~/.claude/logs/webhook-restart.log` and `launchctl list` that the restart happens within roughly a minute and that an unrelated merge running at the same time isn't cut off.