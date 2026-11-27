Now I have enough grounding in the existing infrastructure to write the plan.

## North-star fit

Reuses, rather than adds new machinery, at nearly every layer:
- **`ticket_stages.STAGES_DIR`** (per-ticket `{stage, status, detail, timestamp, machine}` events, already synced across Macs) — the exact pattern `purpose_metrics._pipeline_verify_timeouts`/`_replanned_tickets`/`_prd_dispatches` use to glob and filter. `run_ticket.py:426`'s `ts.record_stage(issue_number, "done", "passed", f"PR raised: {outcome['pr_url']}", **kw)` is the literal, already-written signal for "the pipeline raised a PR" — no new instrumentation needed.
- **`failure_breaker.tripped(project=repo)` / `code_trip()`** for the "breaker tripped" and "stale code" reasons (`lib/health_checks.py:check_pipeline_breaker` already merges local + SSH-remote trips this same way).
- **`~/.claude/logs/jobs/ticket-pipeline.json`** (`job_events.job_run`, per-machine, not synced) for the "a machine guard is refusing" reason — its `steps[].detail` already carries the exact refusal text (`_GUARD_MARKERS` in `ticket_pipeline.py`, plus `memory_guard.guard()`'s "memory is under pressure" message).
- **`tp._unclaimed_ready_tickets(repo)`** (already used by `check_parallel_dispatch`) for the ready-ticket count; **`project_profile.dispatchable_repos()` + `HOME_REPO`** for which projects are in scope.
- **`ticket_agents.due_for_repo(repo)`** for "blocked something else" (a hard deadline), to decide amber vs. red.
- **`health_checks.default_checks()` + `alert_red_checks()`** (ADR 0083/#1123, already wired into `_cli()`) for the "one nudge, never a repeating alarm" requirement — red checks already alert once, repeat daily only while red, and clear silently. No new notification code is needed; staying amber (the normal case) correctly stays quiet.
- Cross-machine shape (SSH to each reachable Mac, skip an asleep one, `_reachable()`) copies `check_pipeline_breaker`/`check_sync_stuck` exactly.

Simplest sufficient approach: one new pure-logic module (`lib/pipeline_purpose.py`) that composes these existing readers into a reason ladder, plus a thin cross-machine wrapper in `health_checks.py` registered in `default_checks()`. No new config, no new state file, no new alert path. Token/compute cost: a few local file globs plus the SSH round-trips the sweep already pays for other cross-machine checks (`CROSS_MACHINE_BUDGET_S`) — no model calls, fully deterministic. It leaves the owner more capable: instead of 50+ ready tickets silently stalling for a day before anyone notices (the 2026-10-29/30 incident), the cause is named automatically the first time it would recur.

**Correction to the ticket's own "North-star fit"**: it says this "reuses... the board's ready list" — the actual reusable function is `ticket_pipeline._unclaimed_ready_tickets`, not something in `ticket_agents` (that module's `ready_elsewhere` is for projects with *no* profile yet, a different case already covered by `check_missing_profiles`). Also "pipeline-failures.jsonl" is only one of three log sources needed — `ticket-stages` and the per-job run log (`jobs/ticket-pipeline.json`) carry signals `pipeline-failures.jsonl` alone doesn't (unconditional verify-timeout record and live guard-refusal text, respectively), matching why `_pipeline_verify_timeouts` was added as a *complement* to the `pipeline-failures.jsonl`-based probe in #1316.

## Decisions

<!-- marvin:decisions -->
### red-threshold: When does a missed purpose also count as "blocked something else" (→ red, per CONTEXT.md's Missed-purpose rule)?
- [ ] A hard due date (`ticket_agents.due_for_repo`, `hard: true`) that is today or already past
- [ ] A hard due date within 48 hours
- [ ] A hard due date within the chosen window (24 hours)
> Recommended: today-or-past — a future hard deadline isn't blocked *yet*; only a missed one is. (Everything else always reports amber, with the reason and fix, never red.)

## Tests first

Against `lib/tests/test_pipeline_purpose.py` (pure logic, fixture log lines — no network, no `gh`) and `lib/tests/test_health_checks.py` (cross-machine wrapper):

**From "How we'll try to break it":**
1. Dispatch off for the project → no finding (project excluded from scope entirely).
2. Zero ready-for-agent tickets → no finding, however old the last PR.
3. A PR raised by a person/chat (no `ticket-stages` "done"/"passed" + "PR raised:" event, e.g. a PR body/commit with no stage record) → still counts as missed (only a pipeline-raised PR clears it).
4. One Mac asleep/unreachable (`reachability` says not green) → that Mac's card reads "asleep", never counted as a failure or a save; the other reachable Mac is still judged normally.
5. Logs missing or corrupt (`ticket-stages` file unreadable JSON, `jobs/ticket-pipeline.json` absent) → `unknown` (grey), never green, never red.
6. Clock skew between Macs → age/window math never goes negative (reuse the same `max(0, ...)` guard pattern as `check_dispatch_lock`'s age calc).
7. A window spanning a restart (no job runs logged because the Mac was off, not because dispatch is broken) → distinguishable reason ("no run was dispatched"), not misreported as a guard/breaker failure.

**From the acceptance criteria:**
8. Replaying the Mac mini's 2026-10-29/30 fixture (repeated `verifying`/`failed`/timed-out `ticket-stages` events, ready tickets > 0, no "PR raised" event) → amber within 24h, reason exactly "the last 3 runs timed out at verifying".
9. Breaker-tripped fixture (`failure_breaker.tripped()` returns a trip for the project) → reason names the signature, most specific first (checked before the stage-failure reason).
10. Guard-refusal fixture (`jobs/ticket-pipeline.json` run steps containing a disk/budget/breaker/"lacks tools"/"memory is under pressure" marker) → reason "a machine guard is refusing: <text>".
11. No-run-dispatched fixture (zero `ticket-stages` events for repo+machine in the window, ready > 0) → reason "no run was dispatched".
12. Everything above absent but still no PR (events exist, none match a bucket) → amber "unknown cause" rather than silently green or crashing.
13. A hard due date already past → red instead of amber, same reason/fix text.
14. A hard due date in the future (not yet due) → stays amber even with ready tickets and no PR.
15. Reused-PR edge case: a "done"/"passed PR raised" event exists but its timestamp is *outside* the 24h window (older PR, nothing new since) → still counts as missed.
16. Two projects, one dispatch-off/one dispatch-on, both with ready tickets → only the dispatch-on one is checked (scope test for `project_profile.dispatchable_repos()` + `HOME_REPO`).
17. Malformed `ticket-stages` JSON for one ticket among several → that file is skipped, doesn't crash the whole check (matches the `ValueError`-only-catch convention in `purpose_metrics`'s probes).
18. SSH to a remote Mac fails/times out → that Mac's card is `unknown`, doesn't take down the sweep or the other Mac's result (mirrors `test_pipeline_breaker_remote_query_handles_unreachable_machines`).
19. Repeated concurrent sweeps (two health sweeps reading the same files at once) → read-only, no lock needed, but must not crash on a half-written `ticket-stages` file (same `(json.JSONDecodeError, OSError)` catch as `read_stages`).

## Task List

1. Add `lib/pipeline_purpose.py`: pure functions `pr_raised_since`, `stage_failure_reason` (reuses `failure_breaker.signature()` for the detail text, defaults N=3 per ADR 0080 I5's existing "3 runs in a row" number — no new threshold invented), `no_run_dispatched`, `guard_refusal_reason` (extends the existing `_GUARD_MARKERS` concept with the memory-guard marker text), and the orchestrating `missed_purpose(repo, machine, now, ready_count, breaker_trips, job_runs, stages_dir)` that applies the reason ladder (breaker → stale-code → guard → stage-failure → no-run → unknown) and returns `None` when a PR was raised or there are no ready tickets.
2. Add `due_blocks(repo, now)` (thin wrapper on `ticket_agents.due_for_repo`) deciding amber-vs-red per the Decision above.
3. Write `lib/tests/test_pipeline_purpose.py` covering all 19 cases above against the pure functions (fixture JSON files under `tmp_path`, no real GitHub/SSH).
4. Add `check_pipeline_purpose(reachability=None, remote=None)` to `lib/health_checks.py`: enumerate `[HOME_REPO, *project_profile.dispatchable_repos()]`, for each repo get `tp._unclaimed_ready_tickets(repo)` and the relevant machines (`MARVIN_MACHINES` for home repo, `profile["machines"]` otherwise), read local `ticket-stages`/`failure_breaker.tripped()`/`jobs/ticket-pipeline.json` directly, SSH each reachable remote Mac for its own `failure_breaker --json` (reuse `_run_failure_breaker_remote`) and job log (new small `_run_job_log_remote`, same `SSH_OPTS` pattern as `_run_sync_log_remote`), skip unreachable ones via `_reachable()`, and build one result dict per (repo, machine) with id `purpose:pipeline@<repo-slug>@<machine>`.
5. Register it in `default_checks()` right after `pipeline:breaker`/`dispatch:parallel`, passing `reach` the same way the other cross-machine checks do.
6. Add the cross-machine wrapper tests to `lib/tests/test_health_checks.py` (local-trip, remote-unreachable, malformed-file cases — mirroring the existing `check_pipeline_breaker`/`check_sync_stuck` test style).
7. Confirm (via the existing `alert_red_checks` test suite, no change needed there) that a result escalated to red for this check's id flows through the existing once-a-day/clear-on-green alert path with no additional code.
8. Update `CONTEXT.md`'s "Missed purpose" section with one line naming this as the pipeline's concrete instance (mirroring how #841's portfolio check would be referenced), and cross-link `docs/adr/0080-the-work-loop-is-one-system.md` I5.