## North-star fit

**Reuses:**
- `health_checks.check_dispatch_lock` (`lib/health_checks.py:119`) — same age-threshold-on-a-JSON-timestamp pattern, reused for the new "scan running long" card instead of inventing a new mechanism.
- `job_events.step()`'s existing update-in-place semantics (`lib/job_events.py:79-86`) — calling `step()` again with the same name already overwrites that step's `detail`/`at` fields, which is exactly the "what is it stuck on, since when" signal AC3 needs; no new plumbing required.
- `conflict_repair.Budget`/`"later"` outcome (`lib/conflict_repair.py:279-304`) — the existing "out of budget, try again next scan" path is extended with a wall-clock check rather than adding a new state machine.
- The `fail()` callable already threaded through `_scan`/`_dispatch_one` (e.g. `lib/ticket_pipeline.py:1092`) — reused to mark a dispatch-loop crash without it silently vanishing.

**Simplest sufficient approach:** reorder six lines of calls inside `_scan` (move the existing dispatch block earlier, unchanged internally) plus a wall-clock check and some elapsed-time logging — no new subsystem, no async job queue, no change to `test_slot.py`/`conftest.py`'s slot architecture (see finding below, deliberately out of scope).

**Where it spends tokens, not saves them:** this is pure infra/reliability work with no LLM calls added; the only new cost is a few extra `time.monotonic()` calls and one more Health check per sweep (cheap, local, no network).

**Leaves the user more capable:** yes — restores autonomous dispatch cadence (161 tickets sitting idle while a scan is stuck is the exact failure north star 5 calls out) and makes the next occurrence self-diagnosing instead of requiring Gil to dig through logs by hand.

**A finding, not a fix (flagged, not chased):** I traced the ticket's own hypothesis ("probably waits on the test slot") through `lib/test_slot.py` and `conftest.py:76-103`. The root conftest **always** redirects a bare `pytest -q` invocation's slot directory to a fresh per-process `TEST_HOME/.marvin-test-slot` (added for #968/#1006, to stop the test suite's own unit tests from blocking on real production merges). `conflict_repair.default_tests()` calls `pytest -q` the same bare way — so it never actually contends with the merge gate's real slot; it just runs a full suite that can independently take up to `TEST_TIMEOUT_S` (25 min). Fixing that redirection to distinguish "testing test_slot.py itself" from "running the real suite as a quality gate" is a real, separate architectural question with its own blast radius (it affects every pytest invocation of this repo, not just conflict repair) — **out of scope here**; I'll recommend it as a follow-up ticket rather than guess at it inside this fix. This ticket's ACs don't require resolving that, only making dispatch not wait and the slow step visible/bounded, both achievable without touching slot/conftest wiring.

## Tests first

From "How we'll try to break it":
1. **A merge holding the test slot for 40 min** → a repair whose `run_tests` call blocks past the per-scan wall-clock budget: the *next* repair attempt in the same scan must return `"later"` without starting, and dispatch (already run earlier in the scan) must be unaffected.
2. **10 conflicted PRs** → with `MAX_PER_SCAN=2` and the new wall-clock budget, only the first attempts actually run; the rest return `"later"`/are left for next scan; no hang, no crash, no quadratic blowup.
3. **GitHub rate-limited mid-step** → a `gh` call inside the loop (`pr list`, `issue list`, or the per-PR `_still_needs_sending_back` re-check) fails mid-iteration: the step finishes, logs the failure, and does not take down the scan or block the steps after it.

Additional misuse the ticket's list didn't name:
4. **Dispatch itself raises** (new risk introduced by reordering) — an uncaught exception anywhere in the circuit-breaker/scanning/dispatch path must not prevent Conflicted PRs / Owner decisions / Parked choices from running afterward; the run is marked `fail()`, not silently swallowed.
5. **Zero conflicted PRs** — instrumentation code path still runs (timing logic touches nothing) and the step detail reads exactly as it does today ("none").
6. **A PR's repair crashes** (existing `except Exception` in `_try_conflict_repair`) — still produces a timed, logged outcome; the timing wrapper itself can't become a second way to crash the loop.
7. **Malformed/empty `gh` JSON output** — existing `try/except (ValueError, KeyError, TypeError)` paths still return `[]` cleanly with the new timing code present.
8. **Health check: job file missing / corrupt / no runs / run already finished / `started_at` missing / scan well under 15 min** — each reads a sane severity (green for normal/idle, never a false amber); a scan genuinely stuck past 15 min reads yellow and names the current step; a pathologically long scan (I'll pick a red tier, e.g. ≥45 min) reads red.
9. **Step-order regression** — update `test_a_scan_with_nothing_ready_leaves_a_run_log_saying_so` (`lib/tests/test_ticket_pipeline.py:218-228`) to the new order, and add a test that dispatch's claim/dispatch calls happen even when `_requeue_conflicted_prs`/`_owner_decisions`/`_parked` are slow or patched to raise.

No owner decisions needed — this is a scoped bug fix with inferable defaults (budget value, red threshold), not a design choice with real alternatives to put in front of Gil. I've called out the one real judgment call (not touching `test_slot`/`conftest` architecture) as a finding above rather than a silent guess.

## Task List

1. **`lib/conflict_repair.py`**: instrument `repair()` with per-phase timing (rebase/resolve, model-assist, `run_tests`, push) returned in the result dict (`timing` key, additive, no existing key removed); add `REPAIR_SCAN_BUDGET_S` (15 min) and a wall-clock deadline on `Budget`; `attempt()` returns `"later"` once the deadline has passed, before calling `do_repair`.
2. **`lib/ticket_pipeline.py` (`_requeue_conflicted_prs`/`_try_conflict_repair`)**: measure elapsed time per PR, fold per-PR durations into the existing stderr `print` lines and the final `step("Conflicted PRs", ...)` detail; emit an in-progress `step("Conflicted PRs", f"PR #{n}: ...")` call before each repair attempt so a stuck scan's Health card can name the PR, not just the step.
3. **`lib/ticket_pipeline.py` (`_scan`)**: extract the circuit-breaker + repo/settings computation + "Scanning tickets" step + dispatch `while` loop (current lines ~945-1038) into `_run_dispatch(step, summary, fail, dry_run)`; call it immediately after `_run_ticket_agents(...)`, before the `if not dry_run:` block containing Conflicted PRs/Owner decisions/Parked choices (which moves to run after it); wrap the call in `try/except` that calls `fail(...)` on an exception so the trailing steps still run.
4. **`lib/health_checks.py`**: add `check_pipeline_scan_duration()` (reusing `check_dispatch_lock`'s age-threshold pattern) reading `~/.claude/logs/jobs/ticket-pipeline.json`'s latest run; yellow ≥15 min, red ≥45 min, naming `steps[-1]["step"]`; register it in `default_checks()`.
5. **Tests**: update the step-order assertion in `test_ticket_pipeline.py`; add tests 1-9 above across `test_conflict_repair.py`, `test_ticket_pipeline.py`, and `test_health_checks.py`.
6. **Recurrence check**: register a probe (following the existing `purpose_metrics.py` pattern used by #1113's `verify-timeout-in-slot-wait`) for "Conflicted PRs step duration" so a repeat shows up without re-reading logs by hand.