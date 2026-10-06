# 0048 — The Metrics tab: tools and skills, usage, pipeline results, for both machines

## Status

Accepted (2026-10-06).

## Context

The tool-usage page (which tools and skills get called, when, and whether it went well) lived as a sub-tab of Health, easy to lose,
and the Metrics tab itself showed only per-subsystem benchmark cards that are empty until something records. Nothing showed how much the
Claude sessions use, which matters now that usage limits decide how much work can run, and every scan covered only the machine the
dashboard happened to run on.

## Decision

The Metrics tab has three sections:

1. **Tools & skills** (moved from Health, widened): per tool, skill, MCP server and subagent, calls, failures, invalid calls, a
   30-day strip (one cell per day), last use, filters by name and by kind of run, the never-fired skills and the newest failures.
2. **Usage** (new): tokens per day stacked by kind of run (pipeline, interactive, subagent), 7 and 30 day totals, the pipeline's
   share, and where it went by project and by pipeline ticket. Output tokens are the default measure; "all tokens" adds the cache counts.
3. **Pipeline results**: the existing benchmark cards, unchanged.

Tools and Usage cover **both machines** and can be narrowed to one. Each machine scans its own transcripts (`lib/tool_usage.py`,
`lib/session_usage.py`) hourly through the `com.marvin.usage-scan` job and keeps the result in `~/.claude/logs/`. Those files are
not synced (they can quote commands and error output). `lib/usage_report.py` builds the merged report: this machine's files, plus the
other machine's read over ssh, asking a reachable peer to rescan when its file is older than 90 minutes. An unreachable peer is
shown as unreachable, never silently dropped.

Token counting de-duplicates by message id: Claude Code writes one transcript line per content block, each repeating the message's
usage (53 lines were 19 messages), so a naive sum overstates usage about threefold.

## Consequences

- One place answers "what is MARVIN doing and what does it cost", across both machines.
- The Usage view is the input for deciding what to move to local models and which tickets burn the most (retry storms show up as one
  ticket far above the rest).
- A project is attributed from the session's working directory; a pipeline worktree is named for its ticket. Sessions in other
  directories fall under the directory's name.
- Not measured: whether the right skill fired for a request, and cost in money (the data has tokens, not prices).
