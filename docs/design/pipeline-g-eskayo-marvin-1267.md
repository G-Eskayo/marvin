## North-star fit

**Reuses, before adding anything:**
- `lib/evidence_capture.py:run_timed` (+ `SlotWaitTimedOut`/`TestTimedOut`) — the exact, already-tested mechanism (marvin#1113) for running a test command with a timeout clock that pauses while `test_slot` says "waiting" and a separate cap on slot-wait time. `lib/project_profile.py:_default_runner` (line 450-452) already wires it in for every other project's verify step. `conflict_repair.default_tests` is the one caller that skipped it — it shells `pytest` straight out via a bare `subprocess.run(..., timeout=TEST_TIMEOUT_S)`, with **zero** `test_slot` participation.
- `lib/test_slot.py:slot()` — same pattern `lib/main_health.py:_run_suite` already uses (`with test_slot.slot("label"): ...`) to queue behind a merge instead of fighting it for CPU/memory.
- `lib/conflict_repair.py:Budget`/`attempt()` — the existing per-scan repair-count budget; I'm adding a matching wall-clock budget next to it, not a new mechanism.
- `lib/job_events.py` `step()` — the exact callback `_scan()` already passes to report "Board discovery", "Owner decisions", etc. Per-PR timing rides the same channel.
- `dashboard/electron/main/working.js:buildWorkingNow` + `dashboard/src/components/DispatchStatusBadge.jsx` (`window.api.working.now()` poll/trigger pattern, `formatElapsed`) — already computes, per running job, `startedAt` and the current step/detail. No new backend plumbing needed for AC3.
- `dashboard/src/components/WorkshopTab.jsx:263-267` — the existing amber "stale" banner markup/Tailwind classes are reused verbatim for the new pipeline-health banner.

**Root cause, found by reading the code (not guessed):** `_requeue_conflicted_prs` → `_try_conflict_repair` → `conflict_repair.repair()` → `default_tests()` runs the MARVIN repo's pytest suite as a plain `subprocess.run(timeout=1500)`, completely outside `test_slot`. `test_slot.py`'s own docstring lists exactly three things that must share its one-at-a-time queue (merge gate, main-health, helpers) — conflict repair isn't on that list and never joined it. `MAX_PER_SCAN=2 × TEST_TIMEOUT_S=25min = 50min` is *exactly* the incident's duration, which is the signature of two repair attempts each running the full 25-minute timeout while thrashing for memory/CPU against a concurrently-running merge gate (the incident notes "merges of the approved freshness PRs were in progress"). Fixing the actual contention, not just capping the symptom, is the simplest-sufficient fix and is what makes AC1 ("what did it wait on") answerable with real data instead of a guess.

**Where this saves tokens/compute:** no new service, no new lock file, no new polling loop on the frontend (reuses the existing 10s poll). The only genuinely new runtime cost is a handful of extra `step()`/log lines.

**More capable, not more passive:** the owner gets a real amber signal naming the slow step instead of silently losing an hour of dispatch; nothing here removes a human decision, it just stops a maintenance step from silently eating the scan.

**Decision needed:** AC2 names three different shapes ("dispatch runs first" / "the step moves out of the scan" / "a time budget, rest to next scan") and doesn't commit to one — these are materially different architectures, so I'm not picking silently. See Decisions below; my recommendation is the time-budget shape, because reordering turns out to require restructuring `_scan()`'s early `return`s (lines ~980, ~992) so Conflicted PRs/Owner decisions/Parked choices still run every scan even when dispatch exits early — a bigger, riskier diff for no extra benefit once the `test_slot` root-cause fix is in.

## Tests to write first

In `lib/tests/test_conflict_repair.py` (real git fixtures, existing style):
1. A merge holding `merges.lock` for a few seconds: `default_tests`'s pytest now goes through `test_slot`, waits, then runs and passes — output contains the `WAITING_RE`/`TOOK_RE` lines.
2. A merge holding `merges.lock` longer than the new slot-wait cap → `attempt()` returns `{"outcome": "later"}`, **not** `"rebuild"`, and writes no `failed_sha` state (so it's retried fresh, not permanently flagged for a machine-busy reason).
3. A genuinely hanging test command (no slot contention) past `TEST_TIMEOUT_S` → still `{"outcome": "rebuild"}` (today's behavior preserved — only slot-wait gets the softer outcome).
4. The dashboard-touching branch (npm install + vitest) also goes through the same `test_slot`/`run_timed` path (today it's a second bare `subprocess.run`, same gap).

In `lib/tests/test_ticket_pipeline.py`:
5. **10 conflicted PRs** (ticket's attack #2): with the wall-clock step budget set low in the test, only as many PRs as fit the budget get processed; the rest are left completely untouched (no label/comment changes) so next scan re-reads them fresh from GitHub.
6. **GitHub rate-limited mid-step** (attack #3): `gh` calls start failing/timing out partway through a 10-PR batch → function returns what it completed, doesn't retry-loop, and the whole call returns well inside the step budget.
7. Step budget is set once per `_requeue_all` call and shared across repos (REPO + `runnable_repos()`), not reset per repo — a slow marvin PR can't give other projects' PRs unlimited extra time.
8. Per-PR timing is reported through `step()` (the same callback already used for "Board discovery" etc.) for every PR considered, not just the ones sent back — asserted via a fake `step` collector.
9. Concurrency: two scans can never run `_requeue_conflicted_prs` at once (already guaranteed by the existing `_scan_lock`, #255) — a regression test documenting this invariant stays true after the refactor.
10. `_still_needs_sending_back`'s re-read-before-send-back still fires correctly when a repair attempt returned `"later"` on a prior pass (a person fixed the PR by hand mid-wait).
11. Empty PR list / malformed `gh` JSON (existing partial coverage) — extend to the new budget-tracking code path so a bad/empty response can't corrupt the deadline bookkeeping.

In `dashboard/test/` (new/extended, mirroring `workshop_now.test.jsx`'s existing `as-of` banner test):
12. A pure classifier (new small lib fn) given a `working.items` entry for job `ticket-pipeline` with `startedAt` 20 minutes ago → amber, naming `current.step`/`detail`.
13. Same job, `startedAt` 2 minutes ago → no amber.
14. A different job (`main-health`) running long → no Workshop pipeline-health banner (scoped to the pipeline scan only).
15. Malformed/missing `startedAt` (bad input) → no crash, fails safe to "no amber" rather than false-alarming.
16. `WorkshopNow` renders the banner text (reusing the amber Tailwind classes already asserted for `as-of`) when the classifier flags amber, and omits it otherwise.

## Decisions
<!-- marvin:decisions -->
### ac2-shape: How should dispatch be guaranteed to never wait behind the Conflicted PRs step?
- [ ] A: Time budget — `_requeue_conflicted_prs` gets a wall-clock ceiling (proposed 10 min); PRs past the ceiling are left for the next scan. Smallest diff, no change to `_scan()`'s control flow. Combined with the `test_slot` root-cause fix below, this is my recommendation.
- [ ] B: Reorder — move the dispatch loop (and the circuit breaker it depends on) to run before the Conflicted PRs/Owner decisions/Parked choices block. Guarantees dispatch unconditionally, but requires restructuring `_scan()`'s early returns (currently those three maintenance steps always run before dispatch, including on scans where dispatch has nothing to do) so they keep running every scan.
- [ ] C: Move it out of the scan entirely — Conflicted PRs becomes its own scheduled job with its own lock, decoupled from `_scan_lock`. Biggest change: new job registration, new Health/Workshop coverage entry, loses the "sent-back ticket can be re-dispatched same scan" behavior entirely (not just delayed by a budget).

### slot-wait-cap: How long should a conflict-repair test run wait for a busy merge before giving up (outcome "later") this scan?
- [ ] A: 5 minutes (proposed default — keeps even two back-to-back repair attempts comfortably under the 15-min amber line)
- [ ] B: 10 minutes
- [ ] C: Something else (text)

## Task List

1. `conflict_repair.py`: add `SLOT_WAIT_CAP_S` constant; rewrite `default_tests`'s MARVIN pytest call (and the dashboard npm-install/vitest calls) to run through `test_slot`-aware `evidence_capture.run_timed` instead of bare `subprocess.run`; catch `SlotWaitTimedOut` and re-raise it past the "genuine failure" path, catch plain `TestTimedOut` and return `(False, ...)` as today.
2. `ticket_pipeline.py`: in `_try_conflict_repair`, add an explicit `except evidence_capture.SlotWaitTimedOut` branch before the generic `except Exception`, mapping to `{"outcome": "later", ...}` so a busy machine never triggers a rebuild/send-back.
3. `ticket_pipeline.py`: add `CONFLICT_STEP_BUDGET_S` (pending decision `ac2-shape`/`slot-wait-cap`); thread a shared deadline through `_requeue_all` → `_requeue_conflicted_prs`'s per-repo, per-PR loop; stop starting new PRs once the deadline passes, leaving the rest for next scan.
4. `ticket_pipeline.py`: thread the existing `step` callback into `_requeue_all`/`_requeue_conflicted_prs`; log one `step()` entry per PR considered with its elapsed time and outcome (parsing `TOOK_RE`/`WAITING_RE` out of the test output to report wait-vs-run split), plus a final summary of how many were deferred by the budget.
5. Write/extend the `lib/tests/test_conflict_repair.py` and `lib/tests/test_ticket_pipeline.py` cases above (1–11); update the existing fixed-arity `run_tests` test lambdas only if the callable contract changes (it shouldn't need to — the timeout values are fixed constants, not threaded per-call).
6. Dashboard: add a small pure classifier (e.g. `dashboard/src/lib/pipeline_health.js`) that, given `working.items`, flags the `ticket-pipeline` job as amber past 15 minutes and returns the current step/detail to name.
7. Wire the classifier into `WorkshopNow` (poll `window.api.working.now()` the same way `DispatchStatusBadge` does, refreshed on the existing `agents` trigger) and render a banner reusing the `as-of` banner's amber Tailwind classes.
8. Write/extend `dashboard/test/workshop_now.test.jsx` (or a new `pipeline_health.test.js`) for cases 12–16.
9. Update `docs/life-of-a-ticket.md` / the relevant ADR note if one of I5's invariants (ADR 0080) needs a line pointing at this new amber signal, since it's a softer, earlier warning than I5's 30-min re-dispatch / 3-failed-runs red.