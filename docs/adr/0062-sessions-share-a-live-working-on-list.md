# ADR 0062: Sessions share a live "working on" list; an edit another session made asks first

**Status:** Accepted (2026-10-09, Gil: "why are we having so many issues with duplicates?"). Plan:
`docs/plans/session-awareness-2026-10-09.md`. Ticket #326.

## Context

Pipeline-to-pipeline coordination exists (claims, the claim tiebreak, parallel-dispatch slots). Nothing told an
interactive session what another session, or the pipeline, was doing. On 2026-10-08/09 two sessions and the
pipeline built the same five fixes in parallel, and the pipeline built ticket #318 a second time (PR #319).

## Decision

- Hooks keep a per-Mac live list (`lib/session_work.py`, `~/.claude/logs/sessions-active.json`): each session's
  latest request and the files it edits, keyed by repo + path (worktrees share the key). Live = active in 45 min.
- Before an interactive session edits a file another live session edited, the edit asks Gil, naming what the other
  session is doing. Once per file per pair of sessions. Any failure lets the edit through.
- A session's first edit in a repo claims the one ready-for-agent, unclaimed ticket its request names
  (`claimed:<machine>`), so the pipeline skips it.
- MR Review marks a PR whose ticket is already closed as probably superseded.

## Consequences

- ~70 ms per edit for the hooks. Hooks load when a session starts: open sessions need a restart to join.
- The list is per Mac; the other Mac's sessions are not seen (the pipeline is covered by claims). A shared-file
  edit that is fine (CONTEXT.md) asks once and then goes through.
