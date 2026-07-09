# 0018 — Auto-discover brain-map's Autonomous Agents from launchd plists

## Status

Accepted (2026-07-09)

## Context

`~/.agents/brain-map/generate.py` builds the desktop wallpaper graph from two sources: the live
`~/.claude/manifest.json` (skills — always current, rebuilt by a hook) and the hand-maintained
`enrichment.json` (everything else, including the "Autonomous Agents" trunk representing launchd
cron jobs). Because cron agents were only representable via a manual `enrichment.json` edit, the
graph repeatedly went stale: five agents added on 2026-07-08/09 (`cross-machine-merge`,
`auto-fix`, `architecture-review`, `cron-health`, `process-quarantine-reviews`) were live and
running for hours before `enrichment.json` was updated to include them — even though
`DesktopLive`'s 30-second poll of `tree-data.json` means the live-reload *mechanism* works fine.
The gap is that the underlying data for this one trunk was never actually live. This is the
second time this exact class of staleness has surfaced.

Alternatives considered:
- Keep hand-maintaining `enrichment.json`, add a reminder/checklist step — doesn't fix the root
  cause, just adds one more thing to forget.
- Require a curated `SUMMARY` constant at the top of every cron script, read directly — correct
  in principle, but means editing every existing script now and enforcing the convention on every
  future one.
- Scan `~/Library/LaunchAgents/com.marvin.*.plist` directly as the live source of truth for
  agent existence and schedule, mirroring how `manifest.json` is the live source of truth for
  skills.

## Decision

`generate.py` scans `~/Library/LaunchAgents/com.marvin.*.plist` at generation time. A plist counts
as a **recurring agent** iff its `StartCalendarInterval` sets only `Hour`/`Minute` — no
`Day`/`Month`/`Year`, since launchd only sets those three together for one specific calendar date
(e.g. `com.marvin.verify-digest-fix`, a one-shot that already fired on 2026-07-07). See
`brain-map/CONTEXT.md` for the term.

For each recurring agent's id (its `Label` with the `com.marvin.` prefix stripped): if
`enrichment.json` has a hand-authored structural entry for that id, use it as-is — this preserves
`daily-digest`'s and `research-colony`'s existing richer `reads:`/`writes:` sub-trees. Otherwise,
synthesize a flat node from the plist's schedule plus a docstring-derived fallback description.

`com.marvin.desktoplive` is excluded with no special-casing: it runs via `RunAtLoad`/`KeepAlive`,
not a calendar interval, so it never matches the recurring-agent shape in the first place.

## Consequences

New recurring cron agents now appear in the graph automatically the next time `generate.py` runs
— no `enrichment.json` edit required, closing the gap that motivated this ADR.

Cost: an agent with no hand-authored override gets a rougher, docstring-derived description until
someone polishes it. Accepted — existence beats prose quality, and the override path still exists
for polish exactly as it already does for skills (`skill_desc_overrides`).

Known gaps this doesn't resolve:
- `generate.py` must still actually run for a new agent to reach the desktop — this ADR fixes
  staleness *within* a run, not the trigger cadence for calling it.
- A future recurring job that (atypically) sets `Day`/`Month`/`Year` for some other reason would
  be silently excluded. Accepted as a low-probability edge case rather than adding a second
  detection heuristic.
