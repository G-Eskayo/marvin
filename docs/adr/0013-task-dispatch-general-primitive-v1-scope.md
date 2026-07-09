# 0013 — Task-dispatch: general primitive, not a cron patch; single-target only for v1

## Status

Accepted (2026-07-08)

## Context

Grew out of a compounding-leverage evaluation earlier the same day, after `exo` (single-model
distributed inference across the Mac Mini and MacBook Pro) was working: what does task-dispatch
still provide that isn't already accomplished? Real, validated gaps found: MARVIN's own cron jobs
(research-colony, daily-digest, cross-machine-merge) are hardcoded per-machine via launchd with no
failover if the assigned machine is asleep, busy, or on a network that blocks what it needs (the
laptop's work network blocking huggingface.co, discovered the same day, is a concrete instance of
"wrong machine for this task right now"); nothing routes an ad-hoc heavy task to whichever machine
is actually available; no mechanism runs independent tasks in parallel across the two machines.

First framing of the scoping question was narrower: "should this just make MARVIN's cron jobs
failover-aware?" Gil's correction, mid-interview: evaluate against the north star — "multiple
computers running MARVIN into one computer" — not just the narrowest fix for the one symptom
already found. A cron-only patch smartens one call site; it doesn't give MARVIN itself (in any
context, including interactive sessions) the ability to say "run this somewhere available," which
is closer to what "one computer" actually means.

Real prior art already built and proven the same day: Tailscale connectivity between the two
machines, `~/.claude/marvin-network.json` device registry, `cross_machine_merge.py`'s `ssh_run()`
(synchronous, timeout-bounded) and `scp_push()`, the wrapper-script pattern for reliable remote env
vars (see `ssh-nohup-env-var-gotcha` memory — inline `export`+`nohup` over SSH doesn't reliably
deliver custom env vars to the child process; a real `.sh` file that exports internally does),
Tailscale's own online/offline liveness signal.

## Decision

**Task-dispatch is a general primitive for location-transparent work execution, not a cron-specific
patch.** Unit of work: an arbitrary shell command — both known consumers (running a cron script; an
ad-hoc headless `claude -p` reasoning task, per the researched NetworkChuck/Terry precedent) reduce
cleanly to a shell command, so the dispatcher needs no special-case knowledge of what it's running.

Three real dispatch modes identified, **only the first is v1 scope**:
1. **Single-target dispatch** — pick one available machine (by liveness + current load, with an
   explicit override always available), run there, get the result back (sync or async, caller's
   choice). The foundation the other two modes need.
2. **Fan-out + merge** — run the *same* task on both machines independently (diversity of results,
   not failover — Gil's framing: "having two different agents doing it each day could mean we get
   more valuable information"), collect once both finish, merge/dedupe/reprioritize by reusing
   `cross_machine_merge.py`'s existing LLM-merge logic directly. Deferred, not built now.
3. **exo-scheduled dispatch** — for work needing genuine split compute (not just parallel
   independent runs), route through `exo`, with real scheduling/visibility so it can be watched
   happening, not silently kicked off. Deferred, not built now.

Single-target dispatch's interface is deliberately kept composable so modes 2 and 3 can layer on
without reworking it later.

Machine selection uses an explicit **dispatch-state file** (`busy`, `task`, `started_at`) each
machine writes locally when a dispatched task starts/finishes, checked over SSH before selection —
not raw OS-level CPU/memory load, which would need an arbitrary busy-threshold with no real data
behind it and would flag normal unrelated use as "busy."

**Failure handling: fail loud, no automatic retry-elsewhere.** Matches the day's recurring theme
(hook-errors.log, cron-health.md, quarantine.md all exist because silent failure is the actual
repeated problem) and avoids the idempotency risk of blindly retrying an arbitrary shell command
that isn't guaranteed safe to run twice.

**v1 build scope is the primitive itself, proven against a real test task — not a rewiring of the
three existing production cron jobs to use it.** Migrating live, currently-working jobs onto a
same-day, freshly-built mechanism is real risk for no immediate benefit; prove it solid first,
migrate one job at a time later, deliberately sequenced as a separate follow-up.

## Consequences

Real near-term cost: three deferred modes (fan-out-merge, exo-scheduling, cron migration) all stay
open threads rather than being resolved today — matches the broader pattern this whole day
established of narrow, proven-first v1s (`auto_fix.py`'s NAMING/VERBOSITY-only scope is the same
shape of decision). Real near-term benefit: a general primitive that composes with what's already
built (data sync via `cross_machine_merge.py`, compute sync via `exo`) rather than a narrow patch
that would need reworking the moment a second real use case (which already exists: the interactive
"run this somewhere available" case) showed up.
