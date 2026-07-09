# 0014 — research-colony fan-out+merge: layer on existing triggers, event-driven completion signal

## Status

Accepted (2026-07-08)

## Context

`research-colony` already runs independently on both machines (two separate launchd triggers,
09:00 daily) — by design, not by accident: Gil wants two independent runs specifically because
"having two different agents doing it each day could mean we get more valuable information."
`cross_machine_merge.py` already merges the resulting research-digest via an LLM pass, but on a
fixed 30-minute buffer (fires at 09:30, hopes both machines finished by then) — a real, current
fragility, not hypothetical.

Two real alternatives were considered for how task-dispatch's deferred "fan-out + merge" mode
(logged in ADR 0013) should actually apply here, once `task_dispatch.py` v1 existed to build on.

**Option A — single orchestrating trigger.** One machine dispatches research-colony to both
machines and waits, then merges. Rejected: this makes the orchestrating machine a new single point
of failure for *triggering* — if it's asleep, work wouldn't start anywhere that day, which is
strictly worse than today's actual resilience (both machines already try independently, regardless
of the other's state).

**Option B — layer on top of the existing independent triggers, make the "wait for both" step
honest.** Accepted. Both machines keep self-triggering at 09:00 exactly as today. What changes:
each machine's research-colony run now executes through `task_dispatch.py`'s local self-targeting
(dispatch to `target=<own device_id>`), which gets busy/done state tracking for free via the
existing exit-trap mechanism in `task_dispatch.py` — zero changes needed to `run_colony.py` itself.

A polled-on-a-schedule check was considered and rejected in favor of an event-driven one: Gil's own
question ("is there a way to trigger it when the previous mechanism is ready?") reframed this
correctly — polling on a timer is still a guess, just a smaller one. Chaining a completion check
onto the end of each machine's own dispatched run (`check_and_trigger_merge.py`) is genuinely
event-driven: whichever machine finishes *second* checks the other's dispatch-state, finds it
idle, and triggers the merge immediately — "last one out closes the door." Whichever finishes
*first* checks, finds the other still busy, and does nothing, trusting the other side's own
check to catch the both-done condition when it finishes.

## Decision

- research-colony's launchd command on both machines becomes a chained pair, run through
  `task_dispatch.py`'s local self-dispatch: `run_colony.py && check_and_trigger_merge.py`.
- `check_and_trigger_merge.py` checks every registered remote's dispatch-state over SSH (reusing
  `task_dispatch.py`'s `_read_remote_dispatch_state`). If any remote is still busy, it exits
  immediately and does nothing. If all are idle, it triggers the merge: directly, if this machine
  is the merge authority (`mobility_class == "stationary"`, matching `cross_machine_merge.py`'s
  existing rule); otherwise by dispatching the merge run *to* the authority machine via
  `task_dispatch.dispatch()`.
- `cross_machine_merge.py` itself is unchanged. Its existing idempotency (`if merged_file.exists():
  skip`) and existing graceful-skip behavior (missing local or remote file → skip, not error) are
  reused as-is, not duplicated — they already handle exactly what a second, later trigger needs.
- The existing 09:30 scheduled trigger stays as a fallback safety net for the case where a machine
  never shows up at all that day (asleep/unreachable all day, so no exit-trap ever fires to catch
  it) — it now just checks whether the merge already happened via the event-driven path first, via
  the same idempotency check, and only proceeds if it hasn't.

## Consequences

Accepted, minor, low-probability edge case: if both machines finish within the same narrow window,
both could observe "the other is idle" and both attempt to trigger the merge concurrently. Not
solved with a distributed lock — `cross_machine_merge.py`'s existing file-existence idempotency
check makes the worst case a redundant LLM merge call occasionally, not a corrupted or double-
written output file. Not worth the added complexity of real distributed locking for that outcome.

Real benefit: the merge now typically fires close to when both machines actually finish (often
well before the old fixed 09:30), not on a fixed guess — while keeping the exact resilience
properties of today's two-independent-triggers architecture, since neither machine's ability to
*start* its own research-colony run depends on the other being reachable at all.
