# 0067 — One brief, built once on the Mini from many feeds, checked item by item

## Status

Accepted (2026-10-15)

## Context

The research colony and the daily digest ran on both Macs, in the hope that two runs would find different things
(the fan-out in [[0014]]). An audit on 2026-10-15 found they don't: both Macs fetched **identical items on all seven
days compared**, and 64–100% of research picks matched; the differences were model randomness. The duplicate runs
doubled model calls, put two quarantine entries a day into the synced `quarantine.md`, and twice stalled the
`~/.claude` sync on merge conflicts (2026-10-10, 2026-10-15). Meanwhile the safety check quarantined the **whole**
research digest whenever it doubted any part, so research reached the morning brief only once from 2026-10-08 to
10-15. The MacBook's model calls failed 9 days in 20; the Mini's, 1.

Alternatives: keep both Macs and give each different feeds (real variety, but two builds still collide and must be
merged); whichever Mac wakes first (no fixed owner, hard to trace); Mini only (no brief on a day the Mini is down).

## Decision

The Mac Mini gathers every feed and builds the single brief before Gil wakes; the MacBook builds it only if the Mini
hasn't, an hour after its usual time. Variety comes from **more feeds**, not more machines. The safety check judges
each brief item on its own: a doubtful item is held back and the next-ranked item takes its slot, so the brief is
never blocked as a whole.

## Consequences

- Half the model calls for these jobs; one quarantine stream instead of two, so no more same-day sync conflicts.
- The brief depends on the Mini being up; the MacBook fallback covers a down Mini, but a Mini that is up and building
  a bad brief is not caught by it (Health has to catch that).
- The fan-out-and-merge step from [[0014]] becomes unnecessary for these jobs.
- Held-back items need a home and a way to ask about them, which the old whole-digest quarantine didn't need.
