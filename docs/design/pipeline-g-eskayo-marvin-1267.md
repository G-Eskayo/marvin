Here is the implementation plan for issue #1267.

## North-star fit

**Reuses before adding anything new:**
- `lib/test_slot.py`'s `slot()` context manager — already built to serialize test runs on a machine and queue politely behind a merge (`merges.lock`), with an existing `say()`-callback convention for "waiting"/"took the slot" lines that marvin#1113 already parses. `lib/conflict_repair.py:default_tests` (lines 112-138) currently runs `pytest`/`vitest` via bare `subprocess.run`, **bypassing this queue entirely** — that's the actual bug behind "probably waits on the test slot": it isn't queuing at all, it's fighting the merge gate's protected run for the same CPU/memory.
- `lib/health_checks.py:check_dispatch_lock` (line 119) — the exact age-threshold/yellow-red template ("busy N min on 'task'") for a new scan-duration check; `check_pipeline_breaker` (line 363) — the exact cross-machine SSH-read template for checking the other Mac's state.
- `lib/job_events.py`'s existing `_Run.step()` (line 79) — a step already gets one log entry at start and is overwritten in place when it finishes, so the *currently-running* step's name is already sitting in `~/.claude/logs/jobs/ticket-pipeline.json` with no new schema needed — AC3's "naming the slow step" is a read, not a new write.
- `dashboard/src/components/WorkshopTab.jsx`'s existing `stale` amber banner (lines 263-267) and `ActivityBanner.jsx`'s `window.api.health.status()` polling pattern — reused verbatim for the new banner's markup/classes and data source.
- `conflict_repair.Budget` (count-based, `MAX_PER_SCAN`) — extended with the same mental model as a wall-clock budget, not a new throttling concept.

**Why simplest sufficient:** three small, independent, already-tested-around changes (instrument → route through the existing slot → reorder+budget) plus one new health check and one UI banner. No new subsystem, no new cron/out-of-scan job, no schema migration on `ticket_stages` or `job_events`.

**Tokens:** no new model calls; instrumentation is clock reads + string formatting. Net effect is likely fewer wasted CPU-minutes (conflict-repair's test runs stop fighting the merge gate for resources).

**Phone-OS direction:** indirect — pipeline reliability/observability, not user-facing, but it protects "nothing breaks silently" and "every machine works, none overloaded," which the bigger vision depends on.

**User capability:** more capable, not more passive — Gil gets a live amber signal plus a real timing breakdown instead of having to SSH in and guess ("Probably the step waits on...").

**No Decisions section:** the ticket poses three alternative shapes for AC2 ("dispatch runs first, or the step moves out of the scan, or it gets a time budget"). These are mechanical engineering tradeoffs, not a product/UX choice only Gil can judge, so I'm resolving it myself below rather than blocking a p1 bug fix on a button-click: do both the reorder *and* the time budget (cheap, independent, each closes a different gap the incident exposed).

### Resolved design for AC2

Move only the `Conflicted PRs` step (the `_requeue_all` call and its two `step(...)` calls at `lib/ticket_pipeline.py:937-939`) to run *after* the dispatch while-loop finishes, i.e. to the very end of `_scan()`. `Owner decisions` and `Parked choices` stay where they are — they're not implicated in the incident and moving them is unrelated risk. New step order: `Code freshness, Board discovery, Onboarding plans, Project catalog, Owner decisions, Parked choices, Circuit breaker, Scanning tickets, [dispatch loop], Conflicted PRs`. This has no data dependency problems: `repos`/`pools` never read `_requeue_all`'s result, so dispatch is unaffected; the only behavior change is that a ticket freshly un-claimed by a requeue is picked up next scan instead of this one — an explicit, acceptable one-hour-later tradeoff, not silent breakage.

On top of the reorder, give `_requeue_all`/`_requeue_conflicted_prs` an optional wall-clock deadline (new `deadline: float | None = None` kwarg, default `None` = unlimited so every existing direct-call test keeps its current behavior unchanged). `_scan()` passes `time.monotonic() + CONFLICTED_PRS_BUDGET_S` (10 min, comfortably under AC3's 15-min scan threshold). Once the deadline passes, the loop stops starting new PR/repo work and reports how many were deferred to next scan — this is what stops a bad step from also blocking the *next* hourly scan's dispatch (today's second real symptom: 16:13/16:22/17:02 all skipped).

## Tests to write first

**Root cause / contention (ticket's hypothesis + "a merge holding the test slot for 40 min"):**
1. `test_conflict_repair.py`: `default_tests` acquires the machine's test slot (`test_slot.slot`, `merge=False`) before running pytest/vitest, instead of calling `subprocess.run` unprotected.
2. `default_tests` waits behind a held `merges.lock` (simulate a marked merge) and only runs after it clears — reproduces "a merge holding the test slot for 40 min" at test speed, not real time.
3. `default_tests` passes straight through without deadlocking when called from inside an already-held slot (`MARVIN_TEST_SLOT` set) — matches `test_slot.slot`'s documented pass-through behavior.
4. Dependency failing: `test_slot` dir unwritable/OSError → `default_tests` fails closed (returns a `rebuild`-style failure `conflict_repair.attempt` already catches), doesn't crash the scan.

**Instrumentation (AC1):**
5. `_requeue_conflicted_prs`/`_try_conflict_repair`: each PR attempt's elapsed time (fetch/rebase/model-resolve/test-run) is recorded into the existing `ts.record_stage(..., detail=...)` call — parseable, not just printed.
6. The `Conflicted PRs` step's `job_events` detail includes total step elapsed time and names the slowest PR + its duration.
7. Each dependency failing: a `gh` call timing out/erroring mid-PR still yields a timing record for that PR (partial, not crashed) and the loop continues to the next PR.

**Reorder (AC2):**
8. Update `test_ticket_pipeline.py:228`'s step-order assertion to the new order.
9. A ticket newly un-claimed by `_requeue_all` *this* scan is not re-dispatched until *next* scan — explicit regression test for the accepted tradeoff (repeats/wrong-order misuse).
10. Dispatch still completes and its started-ticket count is unaffected when `_requeue_all` raises or is artificially slow (dependency failing; proves dispatch is fully off Conflicted PRs' critical path).

**Time budget (AC2 — "10 conflicted PRs" scenario):**
11. With a deadline that expires mid-loop (fake clock), `_requeue_conflicted_prs`/`_requeue_all` stops starting further PR/repo work, returns what was already sent back, and reports how many were deferred — no partial/corrupted label state on the deferred ones.
12. With `deadline=None` (today's direct-call signature, ~20 existing tests), behavior is byte-for-byte unchanged — regression check, not a new test.
13. 10 conflicted PRs, each repair simulated to take a fixed duration, tight budget: only as many are processed as fit; GitHub rate-limited mid-step (a `gh` call failing partway through the PR list) doesn't crash the budget loop and still defers correctly (composes with existing `continue`-on-`gh`-failure paths).

**Visibility (AC3):**
14. `health_checks.py`: new `check_scan_duration`-style check (built on `check_dispatch_lock`'s age-threshold template) reads `~/.claude/logs/jobs/ticket-pipeline.json`; returns `yellow` with the currently-running step's name once a `status=="running"` run's age exceeds 15 min, `green` otherwise.
15. Reads the step name correctly even when only one step has been logged so far (just started) and when the file is missing/malformed JSON (`_unknown`, bad/empty/malformed input case).
16. Cross-machine: mirrors `check_pipeline_breaker`'s SSH read of the other Mac's job log; degrades to `_unknown`/skips cleanly when that Mac is unreachable (dependency failing / wrong machine).
17. A crashed run (age > `job_events.CRASHED_AFTER_S`) still reports amber naming the last step, consistent with "nothing breaks silently."
18. `WorkshopNow` (or wherever it's wired): renders an amber banner (reusing the existing `stale`-banner markup) naming the slow step when the check comes back yellow; renders nothing when green/absent; fails closed (no banner, no crash) when `window.api.health.status()` rejects.
19. Repeated 60s polling ticks update the banner rather than stacking/duplicating it.

## Task List

1. `lib/test_slot.py` / `lib/conflict_repair.py`: route `default_tests`'s pytest and vitest subprocess calls through `test_slot.slot(what=..., merge=False)` instead of bare `subprocess.run`, with graceful failure on a slot/OSError.
2. `lib/ticket_pipeline.py` + `lib/conflict_repair.py`: add per-PR timing to `_try_conflict_repair`/`_requeue_conflicted_prs` and fold total/slowest-PR timing into the `Conflicted PRs` step's `job_events` detail.
3. `lib/conflict_repair.py`: add an optional `deadline: float | None` to `attempt()`/the repair-loop entry points so a caller can bound total wall time.
4. `lib/ticket_pipeline.py`: add `deadline` threading through `_requeue_all`/`_requeue_conflicted_prs`, with early-stop-and-defer logic once `CONFLICTED_PRS_BUDGET_S` (10 min) elapses.
5. `lib/ticket_pipeline.py`: reorder `_scan()` so the `Conflicted PRs` block runs after the dispatch while-loop, at the end of the function; update the step-order assertion.
6. `lib/health_checks.py`: add the new cross-machine scan-duration check (local + SSH, modeled on `check_dispatch_lock` + `check_pipeline_breaker`) and register it in `default_checks()`.
7. `dashboard` (preload/IPC if needed, else the existing `window.api.health.status()` path already covers it): surface the new check as an amber banner in Workshop's Now view, reusing the `stale`-banner pattern.
8. Write/update all tests listed above (TDD: each lands before or with its corresponding implementation change).
9. Run the full pytest suite plus the dashboard's vitest suite (per `CLAUDE.md`'s "full suites before a hand-merge") before raising the PR.