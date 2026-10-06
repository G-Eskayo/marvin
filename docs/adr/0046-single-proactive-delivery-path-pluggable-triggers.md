# 0046 — One proactive-delivery path into the Thread; triggers plug into it

## Status

Accepted (2026-10-06)

## Context

MARVIN Mobile replaces the roadmap's WhatsApp/Telegram companion, whose two jobs were (1) MARVIN
reaching Gil unprompted and (2) Gil handing ideas off by text (now just Chat). Unprompted contact
has several distinct causes — pipeline events, health failures, digests, and (later) gaps in
Gil's calendar. These are separate builds; treating them as iterations of one feature would
couple unrelated work. Today pipeline pings go through Claude Code's `PushNotification` tool
(Remote Control), outside any MARVIN-owned surface.

## Decision

Build a single proactive-delivery path on the mobile backend ([[0042]]): APNs push into the
Thread ([[0044]]), with quiet hours (sunset→sunrise at the phone's location), batching of
non-urgent items, an urgent bypass for health failures, and a record of which messages Gil acts
on vs ignores. Causes are independent triggers. v1 ships event triggers (PR ready, ticket needs an
answer, health, digests); the calendar-gap trigger follows immediately after, using v1's
acted-on/ignored record to tune when an interruption actually helps. Existing pipeline
notifications move onto this path; `PushNotification` stays only as a fallback when the app isn't
installed/reachable.

## Consequences

- New triggers are small: no new delivery, quiet-hours or batching logic per cause.
- Quiet hours need the phone's location (or last-known location) on the backend — a small
  privacy surface that stays on Gil's own machines.
- "Urgent" is a classification someone has to make per trigger; mis-classifying wakes Gil up or
  hides a real outage.
- Two notification paths coexist during migration (app vs `PushNotification`) — risk of
  duplicates until the fallback rule is enforced.
