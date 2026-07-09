# 0019 — Auto-discover brain-map's Infrastructure hooks from settings.local.json

## Status

Accepted (2026-07-09)

## Context

Following the same audit that produced [[0018]] (Autonomous Agents nodes going stale because
they were only representable via a hand-authored `enrichment.json` edit), the Infrastructure
trunk turned out to have the identical problem from the identical cause. `enrichment.json` lists
4 hook script nodes (`rebuild-manifest.py`, `emit-resume-prompt.py`, `qa_session_capture.py`,
`improvement_sweep.py`), but `~/.claude/settings.local.json`'s `hooks` key actually wires up 6:
those four plus `background_review.py` and `skill_activity.py` — the latter being the hook that
writes the activity pulses that make the graph's live "what MARVIN is doing" layer work at all,
which was itself invisible in the graph depicting it.

## Decision

`generate.py` reads `~/.claude/settings.local.json`'s `hooks` key across all event types (not
just `PostToolUse`) as the live source of truth for Infrastructure's hook nodes, the same way
[[0018]] made launchd plists the live source for Autonomous Agents. Each hook command's script
basename becomes the node id (matching the existing naming already in use —
`rebuild-manifest.py`, etc.). The same override-if-present-else-fallback merge rule from [[0018]]
applies: a hand-authored `enrichment.json` entry for that id wins if present, otherwise a node is
synthesized from the hook's trigger (event + matcher, e.g. `PostToolUse: Skill`) and a
docstring-derived fallback description. A script referenced by more than one hook entry is
deduplicated by id.

## Consequences

Infrastructure can no longer silently omit a real hook the way it omitted
`skill_activity.py` — every hook actually wired into `settings.local.json` shows up on next
regeneration with no manual edit required.

Cost and known gaps mirror [[0018]] exactly: `generate.py` still has to actually run for a change
to reach the desktop, and hooks configured only in the global (non-local) `settings.json` — which
is currently empty but is a valid place to add one — aren't scanned by this decision. If that file
starts being used, this decision should be revisited to scan both.
