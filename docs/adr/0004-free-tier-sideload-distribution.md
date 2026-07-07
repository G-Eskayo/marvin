# 0004 — Distribute via free Apple ID + AltStore/AltServer, not a paid Developer account

## Status

Accepted (2026-07-03)

## Context

Native app ([[0002]]) needs a distribution mechanism. Two paths considered: a paid Apple
Developer Program membership ($99/yr, no signature expiry), or a free Apple ID with the
standard 7-day signature expiry that free-tier code signing carries.

AltStore/AltServer (and its fork SideStore) automate the free-tier resign cycle: AltServer
runs on a Mac and silently re-signs the app whenever the phone is on the same WiFi network,
with no manual reinstall step. This removes the *manual toil* of the 7-day cycle entirely.

It does not remove the underlying constraint: the phone must rejoin the AltServer Mac's WiFi
at least once every 7 days for the silent refresh to succeed. This is in tension with
offline mode's own premise ([[0003]]) — a trip off-grid longer than a week could let the
app's signature lapse mid-trip, exactly when offline mode matters most. SideStore may relax
this constraint but that isn't verified.

## Decision

Ship via free Apple ID + AltStore/AltServer automated background resign. Accept the
off-grid signature-expiry risk rather than pay for a Developer account to remove it.

## Consequences

- Zero ongoing cost, no manual resign toil under normal (weekly-ish WiFi contact) use.
- Real, accepted risk: a trip longer than ~7 days without touching the AltServer Mac's WiFi
  network could let the app itself expire while offline — silently defeating the reason
  offline mode exists. Not yet mitigated.
- SideStore's exact refresh mechanism (whether it relaxes the same-WiFi requirement) is
  unverified and worth revisiting if long off-grid trips turn out to be common in practice.
- Reversible later: switching to a paid account if the risk proves real in practice is a
  low-cost change (distribution only, no architecture impact).
