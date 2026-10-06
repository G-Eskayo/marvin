# 0037 — Answering a waiting ticket from the dashboard

## Status

Accepted (2026-10-06).

## Context

A ticket can be waiting on the owner: `needs-info`, or parked by the pipeline after repeated failures (claimed, no longer
`ready-for-agent`). The only way to answer was to say it in a chat or to comment on GitHub by hand and then fix the labels by hand,
because nothing re-queued the ticket after a comment. The agent already reads a ticket's comments before it plans
(`lib/sandbox_orchestration.py`: "Also read its comments"), so the answer itself reaches it; what was missing was the trigger.

## Decision

The ticket detail view in the dashboard has a **Reply** box. Sending it (`boards:input`, `electron/main/ticket_input.js`):

1. posts the text as a comment on the GitHub issue, signed "Reply from the owner" and carrying the marker
   `<!-- marvin:human-input -->`;
2. if the ticket was waiting, puts it back in the queue: `needs-info` is replaced by `ready-for-agent` and `claimed:*` is released;
   a ticket parked after repeated failures gets the same. A human comment already ends the pipeline's failure streak
   (`run_ticket` stops counting at the first non-failure comment), so the next attempt starts clean.

The rules live in one pure function (`src/lib/ticket_input.js`, `planInput`) used by both the screen (it states what sending will do
**before** you send) and the main process, so they cannot disagree. The comment is posted first: if the label change fails the answer
is still on the ticket and the result says so.

Not re-queued, comment only: closed tickets; `ready-for-human` and `wontfix` (a person's, not the agent's); tickets with
`needs-reengagement` (already queued to be rebuilt; the agent reads the comment then); tickets already `ready-for-agent`.

## Consequences

- Answering is one step in the app, and what it will do is visible first.
- The comment marker lets later work (for example the pipeline surfacing "answered" tickets) find owner replies.
- Replying from the dashboard needs the same GitHub credential the rest of the app uses.
