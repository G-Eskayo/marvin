## North-star fit

**Reuses before adding anything new:**
- `dashboard/webhook-server/merge_queue.js`'s `createQueueStore()` — its existing `change()`-based mutator pattern (`add`/`hold`/`markConflict`/`fail`, lines 54–109) gets one more mutator, `resume()`, instead of new storage or a new file format.
- `index.js:362`'s existing `repoOfPr()` to derive the repo from a PR url inside the startup loop — not rewritten.
- `lib/webhook_restart.py` and `lib/dashboard_rebuild.py`'s shared shape: a pure `decide(*, ..., now) -> tuple[str, str]` (action, reason) + a `main()` that gathers facts and prints the reason, with `lib/tests/test_webhook_restart.py`'s `d(**kw)` test idiom. The previous attempt's `decide()` returned `None` with no reason and its code review (PR #1264, non-blocking note on `lib/merge_server_wait.py:31`) flagged exactly this drift from the sibling pattern — fixed here by actually matching it.
- `lib/health_checks.py:1669-1670`'s `MERGE_PORT = 7878` constant and its `merge_service_reachable()` probe convention (GET with a short timeout, any HTTP answer counts) — reused rather than re-declaring the port or re-deriving the probe shape.
- `dashboard/electron/main/merge_ops.js:15`'s `maxMergingMs = 45 * 60_000` as the existing "how long a merge can reasonably run" convention, reused as the wait bound instead of inventing a new number.
- `dashboard/scripts/rebuild_and_install.sh`'s existing habit (lines 12, 31) of shelling out to a `~/.agents/lib/*.py` helper for a sub-step, reused for the new wait step.
- `GET /merge-queue` (`index.js:170-176`, already returns `{repos: {repo: {items, failed, lastMerged, running}}}`) — no new endpoint.

**Why simplest sufficient:** the queue's own startup `kickAll()` (marvin#231, merged before this ticket's 2026-11-04 incident) already re-runs whatever is queued on restart. The two real, confirmed gaps are: (1) `rebuild_and_install.sh` (lines 84-87) restarts the merge server completely unconditionally, with no check for an in-progress merge at all; (2) nothing explicitly re-adds/fronts an interrupted PR's queue entry — it merely survives by accident today. A targeted `resume()` plus a bounded wait helper closes both without a new service, endpoint, or storage format.

**Tokens:** small diff across the same files the first attempt touched, plus directly addressing that attempt's own review notes and its one CI failure, so this attempt should not need further round-trips for the same reasons.

**Capability:** removes a silent stall that previously needed Gil to notice a dashboard card and re-click Approve — more capable, not more passive (north star 3).

**Checked against a ticket-stated fit:** the ticket doesn't state its own north-star fit beyond "North star: 1" — confirmed accurate; it's a bounded automation fix removing an owner-chasing step, not a product decision.

## Earlier-attempt findings folded into this attempt (from issue #1106's comments and PR #1264)

PR #1264 (closed/superseded — this worktree starts fresh from current `main`, which does not contain it) passed verification and CI on everything except one **unrelated, pre-existing flaky test** (`test/merge_stage_relay.test.js > the card on another Mac > two Macs fed the same relayed merge show the same strip, and both end merged` — an `AssertionError` on a deeply-equal check in a file this ticket's diff never touches). That failure is not caused by this ticket's changes and needs no fix here; re-running against current `main` is the correct response (which is what the auto-resend already did).

Its code review passed with **no must-fix issues**, but left seven non-blocking notes and a 62% mutation score. Folding those in as requirements for this attempt:

1. `decide()` must return `(action, reason)` like its siblings (`lib/webhook_restart.py`, `lib/dashboard_rebuild.py`), not a bare string/`None` — the design doc already said this and the implementation didn't do it.
2. The probe must not fail open on a short, easily-hit timeout. `lib/health_checks.py`'s `MERGE_PROBE_TIMEOUT_S = 3` existing convention is still too short for this use (a busy gate step can be slow to answer); use a longer per-request timeout **and** retry at least once before concluding "not running," so a slow-but-alive server doesn't look dead mid-merge.
3. Wait-time accounting must use a monotonic clock measuring the *whole* wait (including request time), not just accumulated `sleep()` calls, so the documented bound and the real one match.
4. `main()`'s poll loop itself must be tested (mutation score missed the loop's `while True:` and its `if result == "restart":` entirely — only `decide()`/`_merge_running()` were tested, not the thing that calls them in a loop).
5. The three queue tests (9–11) must match the ticket's actual break-it cases: resuming must be shown to make the PR run *first* (via `kickAll()`, not just reordering the stored array), resuming twice must be safe, and a PR that merged/closed elsewhere must be dropped, not resumed.
6. The `index.js:498` "not awaited" note is **not acted on**: `createQueueStore()`'s `change()` is synchronous today (plain `readFileSync`/`writeFileSync`), so there is nothing to await; adding `await` or a lock for a hypothetical future async store would be validating a scenario that can't currently happen.
7. The `index.js:497` note (the forwarded dashboard event still carries `state: 'failed'` for a merge that is actually about to resume, so the open dashboard's card and the log line disagree) is real and traced to CONTEXT.md's documented intent (line 901-907: a webhook restart mid-merge is *designed* to read as "interrupted"/failed on the card). Changing what the card shows is a user-visible UI behavior change — per the "No unapproved UI changes" / "Confirm UI interactions first" rule, this goes to Gil as a Decision below rather than being silently changed.

## Decisions

<!-- marvin:decisions -->
### card-state: Should the dashboard card stop showing "failed" for a merge that's being auto-resumed?
- [ ] A: Yes — change the forwarded event so the card reads as queued/resuming, not failed, when `takeInterruptedMerges()` hands it to an auto-resumed PR (touches `dashboard/webhook-server/index.js` and the shared reducer in `dashboard/src/lib/merge_progress.js`; a few existing tests' expectations change)
- [ ] B: No — leave the card's "failed" reading as-is for now (matches the ticket's literal acceptance criteria; the queue still resumes correctly underneath, it's just a stale-looking card), and file a follow-up ticket for the UI text only

## Tests to write first

In `lib/tests/test_merge_server_wait.py` (new, mirrors `test_webhook_restart.py`'s `d(**kw)` idiom) — covers "a merge that takes longer than the wait bound," "two rebuilds in a row," and the misuse cases the ticket's list didn't spell out (malformed/unreachable server, slow-but-alive server):

1. `test_restarts_when_no_merge_is_running` — `decide(running=False, waited_s=0, bound_s=2700)` → `("restart", <non-empty reason>)`.
2. `test_waits_while_a_merge_is_running_and_under_the_bound` — `decide(running=True, waited_s=0, bound_s=2700)` → `("wait", <non-empty reason>)`.
3. `test_restarts_anyway_once_the_bound_is_reached_even_if_still_running` — the ticket's explicit break-it case: `waited_s >= bound_s` with `running=True` still returns `"restart"`, with a reason that says it hit the bound (never blocks forever — the queue's own `resume()` covers the merge that gets interrupted by this).
4. `test_every_decision_carries_a_human_readable_reason` — mirrors the sibling scripts' test, run across all branches of (3).
5. `test_merge_running_false_when_the_server_is_unreachable_after_retrying` — `urlopen` raising `OSError`/`URLError` on every attempt → `False`, never raises.
6. `test_merge_running_true_on_the_first_successful_attempt_after_an_earlier_failure` — `urlopen` fails once then succeeds with `running` set → `True` (proves the retry-before-fail-open fix from note 2, not just fail-open).
7. `test_merge_running_false_on_malformed_json` — non-JSON body → `False`, never raises.
8. `test_merge_running_true_when_any_repo_has_a_running_pr` / `test_merge_running_false_when_nothing_is_running` — `{repos: {...}}` shape parsing, multi-repo.
9. `test_decide_calls_are_independent` — two `decide()` calls back to back with different args give independent answers (statelessness: the concrete reason "two rebuilds in a row" can't corrupt shared state because there is no shared state — each invocation of the script is a fresh, stateless poll against the live server).
10. `test_main_polls_until_restart_then_exits` — monkeypatch `_merge_running` to return `True` twice then `False` and `time.sleep` to a no-op recorder; assert `main()` sleeps exactly twice then returns (covers the previously-untested loop — this is what the mutation score missed).
11. `test_main_exits_immediately_when_nothing_is_running` — `_merge_running` returns `False` on the first call; assert zero sleeps.
12. `test_main_restarts_at_the_bound_even_if_still_running` — `_merge_running` always `True`; with a tiny `bound_s`/`poll_interval_s` injected, assert `main()` still returns once elapsed time crosses the bound (proves the loop, not just `decide()`, honors the bound using the monotonic-time fix from note 3).

In `dashboard/test/merge_queue.test.js` (existing file, same `world()`/`make()` fixtures) — covers "a crash mid-merge" and "an interrupted PR that merged or closed meanwhile," fixed to match the ticket's actual cases per review note 5:

13. `it('resume puts an interrupted PR back in the queue and kickAll() runs it before an earlier real approval')` — approve PR 100 normally (queued, held by `RATE_LIMITED` so it stays queued), then `store.resume(repo, url(101))` for PR 101 (never separately approved — the crash-recovery path), then `await queue.kickAll()`, and assert `w.runs` shows 101 attempted before 100 despite 100's earlier `approvedAt`.
14. `it('resume is idempotent: calling it twice keeps one entry, still at the front')` — call `resume()` twice for the same url, assert the queue has exactly one entry for it and it's still first.
15. `it('a resumed PR that merged or closed elsewhere is dropped on the next kickAll(), never run')` — `store.resume(repo, url(102))` for a PR number the fake GitHub world does not return from `openPrs`, then `kickAll()` → assert `w.runs` never includes 102 and the store no longer lists it (covers `mergeOrder`'s existing `dropped` handling, reused rather than rebuilt).
16. `it('resume clears a stale hold/failed entry for the PR')` — approve a PR that gets held or failed, then `resume()`, assert the hold/failed entry is gone.

In `dashboard/test/merge_gate_progress.test.js` (existing `takeInterruptedMerges` test, ~line 296) — covers the stale-messaging defect (note 7), scoped by the Decision above:

17. If Decision `card-state` = A: extend the existing test asserting the log line says resuming (not "Approve again") **and** the returned event's shape reflects a non-failed outcome (e.g. a `resumed: true` flag or non-`'failed'` state the reducer maps to a "queued/resuming" outcome); add/adjust the matching case in `dashboard/src/lib/merge_progress.js`'s reducer test.
   If Decision `card-state` = B: only the log-line assertion changes; the returned event's `state`/`detail` shape is asserted unchanged (existing test keeps passing as today).

Run the full JS (`npm test` in `dashboard/`) and Python (`pytest lib/tests/`) suites at the end; no metrics-comparison gate applies (build-type ticket, per CONTEXT.md:345-352 — mechanical pass/fail).

## Task List

1. `lib/merge_server_wait.py` (new): `_merge_running(host, port=health_checks.MERGE_PORT, timeout=..., retries=1)` — GET `/merge-queue`, parse `{repos}`, `True` if any repo's `running` is set, retry once before failing open to `False`; pure `decide(*, running, waited_s, bound_s=2700) -> tuple[str, str]` ("wait"|"restart", reason); `main()` — polls on a monotonic clock, sleeping between polls, until `decide()` says `"restart"`, then exits 0.
2. `lib/tests/test_merge_server_wait.py` (new): tests 1–12 above.
3. `dashboard/scripts/rebuild_and_install.sh`: inside the existing `if launchctl print ...` guard (lines 84-87), before `launchctl kickstart -k`, call `"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/merge_server_wait.py"` (blocking); the rebuild/install/relaunch steps above it stay unconditional, per the ticket ("the app itself can still be rebuilt and relaunched meanwhile").
4. `dashboard/webhook-server/merge_queue.js`: add `resume(repo, url, { by = 'auto-resume' })` to `createQueueStore()` — re-adds (if dropped) or moves the item to the front (`approvedAt` below every current item's), clears any stale `hold`/`failed` entry for that url.
5. `dashboard/webhook-server/index.js`: extract `const queueStore = createQueueStore()` (currently inlined at the `mergeQueue` construction, line 447), pass it as `store: queueStore`; in the startup loop (`takeInterruptedMerges()`, line 496), derive `repo = repoOfPr(url)` and call `queueStore.resume(repo, url)` when non-null, before/alongside `mergeQueue.kickAll()` already runs.
6. `dashboard/webhook-server/merge_progress.js`: change `takeInterruptedMerges()`'s logged sentence from "Approve again" to text reflecting automatic resume. If Decision `card-state` = A, also change the returned event's shape so it no longer forwards a bare `state: 'failed'`; propagate the matching reducer change into `dashboard/src/lib/merge_progress.js`. If = B, leave the event shape untouched.
7. `dashboard/test/merge_queue.test.js`: tests 13–16 above.
8. `dashboard/test/merge_gate_progress.test.js` (and `dashboard/src/lib/merge_progress.js`'s own test file if Decision = A): test 17 above.
9. Run the full `npm test` (dashboard) and `pytest lib/tests/` suites; confirm nothing else regresses.