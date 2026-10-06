# 0041 — MARVIN Mobile ships via the paid Developer account + TestFlight, private, never the App Store

## Status

Accepted (2026-10-05). Supersedes [[0004]].

## Context

[[0004]] chose a free Apple ID + AltStore/AltServer weekly re-sign to avoid the $99/yr Developer
Program, accepting that a >7-day off-grid trip could expire the app exactly when offline mode
([[0003]]) matters most. Since then Gil has joined the paid program for clarity-captions
(clarity-captions ADR 0009), so the cost that drove 0004 is already paid. The paid account also
unlocks APNs push, which Chat needs to reach Gil proactively (the job the WhatsApp/Telegram
companion idea was for).

## Decision

Sign MARVIN Mobile with the existing paid Developer account and install via TestFlight. Single
user, private; no App Store submission.

## Consequences

- No 7-day signature expiry — 0004's accepted off-grid risk is gone.
- Push notifications become available to the app.
- TestFlight builds expire after 90 days, so a build must be pushed at least that often (far
  looser than 7 days, and normal development will exceed it anyway).
- Ties MARVIN Mobile to the same account renewal as clarity-captions.
