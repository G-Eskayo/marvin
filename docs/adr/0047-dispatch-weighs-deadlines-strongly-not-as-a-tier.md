# 0047 — Dispatch weighs project deadlines strongly, as a weight not a strict tier

## Status

Accepted (2026-10-06)

## Context

The ticket pipeline chose its next ticket by `priority:pN` label, then oldest first. No ready ticket
carried a priority label, so dispatch was effectively oldest-first everywhere. Deadline scoring existed
(`score_ticket`) but only fed the prioritize ticket agent's *proposals* (propose-only until 2026-10-12),
so clarity-captions' hard 2026-10-25 deadline never reached dispatch. Even then, a hard deadline more than
14 days out scored +4, about the same as a ticket being 40 days old.

Gil asked for tickets with sooner deadlines to get priority over non-deadline work. Two shapes considered:
a strict tier (every hard-deadline ticket before any other) or a strong weight. Gil chose the weight, so a
genuinely high-leverage bug elsewhere can still slip in ahead.

## Decision

Dispatch orders ready tickets, within a repo and across repos, by: priority label (a person's or the
prioritizer's explicit choice) → urgency score → age. The score is `score_ticket`, with its project's
deadline from the shared catalog overrides. The hard-deadline weight is raised and starts earlier:
+30 (≤3 days), +24 (≤14), +16 (≤30), +8 (≤60), +4 beyond. Soft deadlines are unchanged.

## Consequences

- A hard-deadline project's tickets go ahead of ordinary work weeks out; a bug that unblocks several tickets
  can still outrank a deadline that's more than a month away.
- The prioritize agent's proposals use the same score, so its labels and dispatch agree.
- A priority label still beats everything, so `p0` remains the escape hatch.
- An unreadable catalog falls back to scoring without deadlines rather than stalling dispatch.
