# 0033 — Health monitoring absorbs cron_health.py; coverage is auto-discovered, not hand-listed

## Status

Accepted (2026-10-01)

## Context

A single session (2026-10-01) surfaced a cluster of infrastructure failures that each went
undetected for days to weeks: an empty ChromaDB collection silently degrading `route.py`'s
embedding classifier to its 28%-accurate keyword fallback (unknown duration), a missing
`~/.claude/.oauth-token`/`.gh-token` on the laptop blocking the entire ticket pipeline there since
~Sep 1, a stale `dispatch-state.json` busy-lock blocking the hourly pipeline for 15 days, and two
runaway ticket-retry storms (6,900+ and 1,139+ sessions) that a 3-consecutive-failure guard now
caps but that nothing detected while they were spiraling. None of these were exotic — each was a
simple, checkable fact (a file exists and parses, a collection has N>0 rows, a lock's age is under
some bound) that nobody was checking.

`~/.agents/lib/cron_health.py` already exists and does real work: it scans job logs for failure
patterns and checks cross-machine git convergence/integrity, writing `~/.claude/logs/cron-health.md`
for the session-start hook to read. Two options were considered: build a new, separate health-check
system alongside it, or extend it into something more general and absorb its existing checks.

A parallel system was rejected for two reasons. First, it directly violates the project's own
"check for reuse before building" standard — `cron_health.py`'s log-scanning logic is already
correct and battle-tested; nothing here needs reinventing, only generalizing. Second, two systems
independently deciding "is daily-digest healthy" would drift, and the dashboard tab is specifically
meant to be the trustworthy answer to "what's actually broken" — a second, slightly-different answer
sitting next to it defeats the purpose.

While scoping coverage for the new system, `cron_health.py`'s own `JOBS` dict was found to be
exactly the blind-spot pattern this feature exists to prevent: 5 hand-listed jobs against 14 real
`com.marvin.*`/`com.giles.*` launchd jobs, with `ticket-pipeline` — the subsystem that spent the
whole session spiraling — not present in it at all. A hand-maintained inventory was rejected for
the new system on this direct evidence, not in the abstract.

## Decision

The health-monitoring system is one extensible framework, not two. `cron_health.py`'s existing
checks (job log-scanning, cross-machine convergence/integrity) are migrated into it as the first
entries in a growing check registry, continuing to also feed the existing session-start markdown
output so nothing regresses for that consumer. Coverage is computed by enumerating MARVIN's actual
infrastructure directly from its authoritative sources (the real launchd plist directory, the
machine registry, `code_sync.py`'s synced-repo list) and diffing against registered checks, not by
trusting a maintained list to stay current.

## Consequences

Every job/machine/repo this enumeration can see gets either a check or a visible "unmonitored"
marker — the blind spot `cron_health.py` had is structurally harder to repeat, since adding a new
launchd job makes it show up as uncovered automatically rather than silently invisible.

This does not solve detection of a failure category nobody has instrumented as a number or log
line at all (true novelty, as opposed to an un-checked-but-enumerable thing) — a deliberate,
acknowledged ceiling, addressed partially (not fully) by the numeric-anomaly layer
([[0023]]-adjacent reuse of `metrics_registry.py`'s compare primitive, applied generically to any
check that emits a tracked number) landing in the same v1. A further LLM-review layer (periodic
"does anything in the aggregated health picture look wrong" pass, same pattern as
`self-improve`/`architecture-review`) was deliberately deferred out of v1 — it has a real,
recurring per-run token cost, and should be added once the numeric-anomaly layer's actual gaps are
observed, not speculatively.

Absorbing `cron_health.py` means its existing daily cadence is superseded by the new scheduler's
15-minute default (see implementation plan) — a job whose own cadence is daily (e.g. `daily-digest`
itself) keeps its own staleness tolerance regardless of how often the scanner polls it, per the
Staleness gradient term in `CONTEXT.md`.
