## North-star fit

- **Reuses, before adding anything:**
  - `dashboard/webhook-server/merge_queue.js`'s existing disk-persisted queue + `mergeQueue.kickAll()` on startup (`index.js:510`, wired since PR #231, 2026-10-30). This mechanism *already* re-runs a merge that was `running` when the process died — proven by the existing, passing test `dashboard/test/merge_queue.test.js:233` (`'a restart mid-queue picks up where it was...'`). I am not building a new resume mechanism; I'm closing the one concrete way the existing one can stall, and fixing the stale "Approve again" messaging that no longer matches what the queue actually does.
  - `lib/webhook_restart.py`'s existing pure-`decide()` + `_facts()` + `main()` pattern (already the one place that force-restarts the webhook via `launchctl kickstart -k`, already unit-tested in `lib/tests/test_webhook_restart.py`). I extend it with a bounded wait instead of inventing a bash curl-poll loop, so `rebuild_and_install.sh` stays thin (it already shells out to `error_log.py`/`code_sync.py` the same way).
  - `lib/health_checks.py:1695` (`merge_service_reachable`) / `peer_care.py`'s `WEBHOOK_PORT = 7878` pattern for reading the webhook's HTTP surface from Python without inventing a new client.
- **Simplest sufficient approach:** a bounded poll of the webhook's own `GET /merge-queue` (`running` field, already exposed, `index.js:170-177`) from the one script that's about to kill the process — no new protocol, no new persisted state.
- **Tokens/compute:** spends a little (one new Python function + a handful of tests); saves more than it spends by preventing a second "owner has to notice and re-click Approve" cycle per incident, and by giving `lib/webhook_restart.py`'s other (currently unguarded) callers a ready-made safe primitive if the owner wants it.
- **Phone-OS direction:** more reliable, unattended merge pipeline — directly serves "nothing may break silently."
- **User capability:** this is pure automation of a mechanical babysitting task (re-clicking Approve after a restart); it does not remove any judgment call from the owner, so it leaves him more free, not more passive.

**Existing-pattern check against the ticket's own stated fit:** the ticket's "What to build" implies AC2 needs new resume logic. Code review shows the resume logic already exists and is tested; the real, verifiable gap is narrower: `createQueueLoader` (`dashboard/webhook-server/merge_facts.js:126-138`) is the only place in that file where `exec('gh', ...)` calls carry **no** `timeout`, unlike every sibling call in the same file (30s/90s). An unbounded `gh pr list`/`gh issue list`/commit-sha lookup can hang `evaluate()` forever, which holds `drain()`'s `busy` lock for that repo forever — `mergeQueue.kickAll()` then never resolves for that repo, and nothing resumes until the owner's own trigger (Approve) happens to land after the hang clears. That's a corrected, narrower version of the ticket's stated fit, not a confirmation of it as written.

## Tests to write first

**A. `rebuild_and_install.sh` / `lib/webhook_restart.py` (AC1 — "a rebuild during a merge restarts the merge server only after that merge ends")**

In `lib/tests/test_webhook_restart.py`:
1. `merge_running()` is true when any repo in `GET /merge-queue`'s `repos` map has a truthy `running`.
2. `merge_running()` is false when nothing is running.
3. `merge_running()` is false (not an exception) when the webhook is unreachable (connection refused) — nothing running means nothing to wait for.
4. `merge_running()` is false (not an exception) on a malformed/non-JSON body or an unexpected shape (`repos` missing or not a dict) — misuse/stale-state case.
5. `wait_for_merge_idle()` returns `True` at once when nothing is running (no sleep called) — ticket's "two rebuilds in a row" base case: a rebuild with nothing in flight must not stall.
6. `wait_for_merge_idle()` polls (injected `check`/`sleep`) while running, then returns `True` once it clears.
7. `wait_for_merge_idle()` gives up and returns `False` once the bound elapses (ticket's "a merge that takes longer than the wait bound") — must not wait forever.
8. `restart_now()` waits, then kickstarts the launchd job, when the wait reports idle.
9. `restart_now()` still kickstarts (does not stall the rebuild indefinitely) when the wait gave up after the bound, and logs that it gave up.
10. `restart_now()` called twice back-to-back both complete and both kickstart (ticket's "two rebuilds in a row") — no shared state from the `--force` path blocks the second call the way `decide()`'s 6h backoff would.
11. Existing `decide()`/`_facts()`/cron tests in the same file are untouched and still pass (the new `--force` path bypasses `decide()` entirely; it never changes cron behavior).

**B. `createQueueLoader` robustness (AC2 — closing the hang that stops `kickAll()` from ever resuming)**

In `dashboard/test/merge_queue_main_state.test.js`:
12. the `gh pr list` call passes a bounded `timeout` option (mirrors `merge_box_runner.test.js:96`'s `toHaveBeenCalledWith(..., { timeout: ... })` style).
13. the `gh issue list` call passes a bounded `timeout` option.
14. the engine-repo's `commits/<base>` sha lookup passes a bounded `timeout` option.

**C. Startup messaging (part of AC2 — "instead of 'Approve again'") — see Decision `ui-copy` below for whether this ships in this PR**

If yes:
15. `takeInterruptedMerges()` marks an entry `resuming: true` (and logs "...resuming automatically", not "...Approve again") when its url is still present in the merge-queue store.
16. an interrupted entry no longer present in the queue store (crashed before `store.add()`, or dropped because it merged/closed elsewhere — reuses the existing drop path, `merge_queue.test.js:248`) still reports "Approve again": there's genuinely nothing left to resume it.
17. the dashboard reducer/`prState.js` renders the "resuming" case distinctly from the "needs Approve" case (no stale "Approve again" button for a merge that's already back in the queue).

**Already covered, not duplicated** (ticket's break-cases that existing tests already prove): "a crash mid-merge" is `merge_queue.test.js:233`; "an interrupted PR that merged/closed meanwhile is dropped, not re-run" is `merge_queue.test.js:248`. "A person's mistake" (re-clicking Approve on an already-auto-resuming PR) is already a safe no-op via `store.add()`'s once-per-url semantics — I'll add one explicit regression test for it rather than assume.

## Decisions
<!-- marvin:decisions -->
### wait-bound: How long should the rebuild wait for a running merge before restarting anyway?
- [ ] A: 60 minutes (the gate's own worst case: `GATE_TIMEOUT_MS` = 40 min, extendable by half under load, `dashboard/webhook-server/merge.js:818`)
- [ ] B: 45 minutes (matches the dashboard's existing "Merging…" stream-timeout language)
- [ ] C: a shorter fixed bound (e.g. 15 minutes) — restart is more important than letting a long merge finish, since the merge resumes by itself anyway

### other-callers: `launchctl kickstart -k` on this same webhook is also called unguarded from `lib/webhook_restart.py`'s 30-min staleness cron and from `lib/peer_care.py`'s remote `restart-service` health remediation (SSH to a peer Mac). Both share the exact defect this ticket fixes. Should this PR also route them through the same wait-for-idle guard?
- [ ] A: Yes, wire all three callers now — same primitive, same fix, one PR
- [ ] B: No, keep this PR scoped to the rebuild path only; file a follow-up ticket for the cron and peer-care paths

### ui-copy: AC2 says the interrupted merge resumes "instead of 'Approve again.'" The backend resume is already real once the gh-call timeout fix lands; the dashboard's "interrupted" card still hardcodes "Approve again" (`prState.js`, `merge_ops.js`'s `INTERRUPTED_REASON`) regardless. Should this PR also update that messaging/state to say "resuming automatically" when the PR is still queued?
- [ ] A: Yes, update the card copy and state in this PR (adds tests 15-17 and touches `dashboard/src/lib/merge_progress.js`, `prState.js`)
- [ ] B: No, ship the backend fix now; file a follow-up ticket for the dashboard copy

## Task List

1. `lib/webhook_restart.py`: add `merge_running()` (GET `/merge-queue`, port 7878, bounded request timeout; unreachable/malformed → `False`).
2. `lib/webhook_restart.py`: add `wait_for_merge_idle(timeout_s, poll_s, check=merge_running, sleep=time.sleep, now=time.monotonic)`, pure/injectable for tests.
3. `lib/webhook_restart.py`: add `restart_now(reason, wait_timeout_s)` — calls `wait_for_merge_idle`, logs the outcome to the existing `LOG_FILE`, then runs the existing `launchctl kickstart -k` call; always restarts even after giving up the wait.
4. `lib/webhook_restart.py`: add a `--force --reason "<text>"` CLI path that calls `restart_now()` directly, bypassing `decide()`'s staleness/backoff logic (which doesn't apply to a deliberate post-rebuild restart).
5. Write tests 1-11 in `lib/tests/test_webhook_restart.py` before implementing steps 1-4 (TDD).
6. `dashboard/scripts/rebuild_and_install.sh`: replace the unconditional `launchctl kickstart -k` block with a call to `"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/webhook_restart.py" --force --reason "rebuild installed new code"`; leave the build/install/relaunch steps above it untouched (they run regardless of merge state, per the ticket).
7. `dashboard/webhook-server/merge_facts.js`: add a bounded `timeout` option (matching the file's existing 30s/90s convention) to the three unguarded `exec('gh', ...)` calls in `createQueueLoader`.
8. Write tests 12-14 in `dashboard/test/merge_queue_main_state.test.js` before step 7.
9. Add the explicit regression test for "re-approving an already-queued, about-to-resume PR is a safe no-op" (`merge_queue.test.js`).
10. Apply the owner's `wait-bound` decision as the `MERGE_WAIT_TIMEOUT_S` constant (with a comment citing `GATE_TIMEOUT_MS`).
11. If `other-callers: A` — wire `lib/webhook_restart.py`'s cron `main()` and `lib/peer_care.py`'s `restart-service` action through `restart_now()`/`wait_for_merge_idle()` too, with their own tests.
12. If `ui-copy: A` — implement tests 15-17 and the corresponding changes in `merge_progress.js` (`takeInterruptedMerges`, add a `stillQueued` predicate param), `index.js` (wire a queue-presence check before forwarding the interrupted ping), `dashboard/src/lib/merge_progress.js` (reducer), and `prState.js` (card copy/state).
13. Run the full dashboard vitest suite and the full Python pytest suite (not a filtered subset) before calling this done — per "full suites before a hand-merge," and because this ticket's prior two attempts failed verification purely on test-slot contention, not logic; keep the actual test run itself targeted/fast where possible so it doesn't become the next contended slot.
14. Open the PR naming `Closes #1106`, with the two Decisions above in the Decisions format so Approve can gate on them if still unanswered.