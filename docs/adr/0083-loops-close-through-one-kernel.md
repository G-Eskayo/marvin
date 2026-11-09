# 0083 — Loops close through one kernel: one alert path, a loop registry, one inbox, a Loops panel

## Status

Accepted (2026-11-04: Gil approved the plan on marvin#1123 and answered its Decisions). Design:
[docs/design/1123-loop-kernel.md](../design/1123-loop-kernel.md). Builds on [[0046]] (one proactive-delivery path),
[[0059]] (output contracts), [[0068]] (proposals), [[0080]] (the work loop's invariants, I5) and [[0033]] (one health
framework). Amends [[0017]] on format only: suggestions become one file per item, and the priority order becomes a
sort applied when they're read.

## Context

An audit of live state on all three machines (2026-11-04) checked 34 feedback loops. One was complete. Almost every
loop *noticed*. What was missing was the step after: an alert or an action, a check of the real outcome, and an honest
record. Sync was broken for 23 hours and the live site was down for 18 hours that week, and nobody was told. Health
went red, and the notifier logged "told the owner" whether or not anything was delivered.

The machinery was duplicated too: 3–4 ways to send a notification (`notify.py`, `mr_notification._fire`,
`disk_forecast_notify.py`'s own copy, `peer_care`'s), 9 inbox piles in different formats, and 4 parsers for one of them.

## Decision

1. **One alert path.** `mr_notification._fire` is the only fan-out (desktop, dashboard, and a phone slot).
   `notify.notify` calls it. Each channel's real result is recorded as a `job_events` run of job `alerts`, never a
   fixed "told". Callers alert on a **change** (an item turning bad, changing, or clearing) through one keyed memory,
   `alert_on_change`, with one reminder a day while an item stays bad.
2. **The phone slot stays empty until MARVIN Mobile's Apple push (#958).** Until then, alerts go to the desktop and
   the dashboard. This is Gil's answer on #1123, and it moves #958 into Tier 1. The per-alert headless Claude
   PushNotification call is removed. ADR 0046's path is where the slot is filled.
3. **A loop registry** (`config/loops.json`, read only by `lib/loops.py`). Each loop declares what it watches, when it
   counts as broken, its action, its verify signal, its owner and its fix (`{level, kind, arg}`, the #874 shape).
   Status (closed, stalled, broken, not wired) is derived each time from `job_events`, the health checks and the
   output contracts, never stored.
4. **Every scheduled job reports through `job_events`.** `lib/job_report.py` wraps any command. A non-zero exit, a
   `REFUSING` line or a skip caused by an error counts as a **failed** run. `job_units` applies it to every
   `config/jobs` job. A job that doesn't report shows its loop as not wired.
5. **One inbox.** `lib/inbox.py` stores one JSON file per item per pile, using the proposals store's rules (ADR 0068).
   It is the only parser. The piles move into it one at a time; suggestions and the improvement queue go first.
6. **Vitals shows and fixes loops.** A Loops view lists every loop's status and last full cycle, with one fix button
   from a fixed set: re-run, re-login, install the missing job, roll back, file a ticket, answer the Decision.

## Consequences

- One place to change how MARVIN reaches Gil. When #958 lands it adds one channel, and every alert gets it.
- Loss: until #958, the "MR ready" and "needs you" pings no longer reach the phone through Claude's push. They go to
  the desktop and the dashboard only.
- The first health sweep after this lands sends one batched alert for everything already red. After that, alerts come
  only on a change, plus one reminder a day.
- Each Mac alerts for what it sees, so Gil is told at whichever Mac they are using. The alert memory is per Mac (logs
  aren't synced), so the same item can alert once on each.
- The registry can drift from reality. Tests check that every loop's job is a known job and that every field parses,
  and the panel shows "not wired" instead of guessing.
- Moving the remaining 7 piles is Phase 2 work. Until each one moves, its old file and parser stay.
