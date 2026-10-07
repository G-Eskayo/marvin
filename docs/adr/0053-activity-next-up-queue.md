# 0053. Activity tab: the "Next up" queue, and no Docs button

Date: 2026-10-07. Status: **accepted** (Gil asked for it 2026-10-07).

## Context

The ticket scanner works from one ordered list: every project's `ready-for-agent` tickets that are unclaimed, not
pinned, unblocked and with no work already done, ordered by priority label, then urgency score (deadlines weigh
heavily, ADR 0047), then age. Nothing showed that list, so "what will it pick up next, and why that one?" meant
reading a scan log. The Activity tab showed what is running on each device and each project's board, never what is
waiting to run.

The "Docs →" button beside the project chips was a misreading of an earlier request (a ticket links to docs from its
own page already); Docs is a tab of its own.

## Decision

1. **A "Next up" strip on Activity**, above the project boards: the scanner's own queue across all dispatchable
   projects, in the order it will dispatch, each row showing position, project, ticket (number + title), priority and
   the machines allowed to run it. The first row is marked as what the next scan takes.
2. **One source of truth.** `lib/ticket_queue.py` builds the queue by calling the scanner's `_unclaimed_ready_tickets`
   and `_order_key`, so the strip cannot drift from what the scanner does. It prints JSON; the dashboard asks for it the
   way it asks `device_status.py` for device rows (short cache, failure shown as an error, never as an empty queue).
3. **The queue is read-only.** Reordering is done with labels (`priority:p0`-`p3`) as today; the strip does not
   invent a second way.
4. **Remove the Docs button** from Activity.

## Consequences

- A ticket that is ready but not in the strip is explained elsewhere (blocked, claimed, pinned, work already exists);
  the strip shows only what would run.
- When parallel dispatch (ADR 0052) lands, the strip's "next" marker becomes "next N".
