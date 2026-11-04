# Session-start checklist

What used to be a 12-step prose checklist in `~/.claude/CLAUDE.md` — read by
Claude at the top of every session, with no guarantee it actually got
followed (a rushed reply, a compacted context, or plain model variance could
skip a step silently). As of 2026-07-14, steps 1–11 are a deterministic
`SessionStart` hook instead: `~/.agents/lib/session_start_report.py`, wired
in `~/.claude/settings.local.json` after the existing code-sync-pull +
`check_remote_session.py` chain. It runs every session regardless of what
the model does, and its stdout becomes session context automatically.

This file is the human-readable description of what it checks and why.
CLAUDE.md only carries a one-line pointer here — the full checklist isn't
in CLAUDE.md's instruction block on purpose, so Claude doesn't also try to
perform these steps by hand each session (duplicated tool calls, duplicated
context, and a manual re-read potentially disagreeing with what the hook
already reported).

## What it checks, per session

| # | Check | Source | What it reports |
|---|-------|--------|------------------|
| 0 | Identity banner | `machine_profile.machine_label()` + live `git rev-parse --short HEAD` on `~/.agents` and `~/.claude` + count of `~/.claude/commands/*.md` | Single verifiable line — `MARVIN active — <machine> · agents@<hash> · claude@<hash> · <N> skills wired` — always the first line of stdout. Added 2026-07-14 so a session can be confirmed as genuinely running MARVIN's infra by checking real, checkable state, not just a static greeting. CLAUDE.md instructs Claude to open the first reply of every session with this line verbatim. |
| 1 | Handoff | `~/.claude/handoffs/*.md` | The most recent handoff (if ≤7 days old) as a pointer: file name, age, its title line and "read it before resuming". Its full text never fit Claude Code's hook cap (see below) |
| 2 | Suggestions | `~/.claude/suggestions.md` | Count of `**Status**: pending` entries |
| 3 | Lexicon | `~/.claude/lexicon.md` | Every term's name and the file to read for its definition (the Full Memory shape: index always, text on demand) |
| 4 | Improvement queue | `~/.claude/improvement-queue.md` | Count of queued `- **[...]**` items |
| 5 | Quarantine | `~/.claude/quarantine.md` | Runs `process_quarantine_reviews.process()` first (feeds checked approve/deny/modify boxes into calibration), then counts remaining unresolved entries |
| 6 | Hook errors | `~/.claude/logs/hook-errors.log` | Count of entries in the last 24h |
| 7 | Cron health | `~/.claude/logs/cron-health.md` | Contents of the "## Latest" block, unless it says "All monitored jobs ran cleanly." |
| 8 | Auto-fix log | `~/.claude/auto-fix-log.md` | Most recent entry, if within the last 24h |
| 9 | Sync log + git conflicts | `~/.claude/sync-log.md` (informational only) + live `git status`/`git stash list` on `~/.claude` and `~/.agents` (authoritative) | Latest sync-log activity, plus **live** conflict/stash state — deliberately NOT decided by scanning log text for the word "CONFLICT", because a resolved conflict's log line stays inside the 24h window and would falsely keep flagging as open. See the docstring on `check_git_conflicts()` for why. |
| 10 | Daily digest | `~/.claude/daily-digest/<today>.md` | Whether today's digest exists |
| 11 | Research digest | `~/.claude/research-digest/<today>.md` | Whether today's digest exists, plus item/correlation counts |

## Size: the report must fit Claude Code's hook cap (marvin#1037)

Claude Code caps a hook's stdout at 10,000 characters. Over that it saves the output to a file and puts only
the path and the first 2,000 characters in context, and never asks Claude to read the file. Until marvin#1037
the report was 12.8-15.4 KB, so sessions saw the banner, the checklist and a sliver of the lexicon, and never
the rest of the lexicon or the handoff (bench Run 31's transcripts show the preview). Now:

- the report is kept under `BUDGET` (8,000 characters, leaving room for the other commands in the same
  SessionStart chain, whose stdout counts toward the same cap);
- the morning brief stays first but is cut at `BRIEF_MAX` (3,500) so the checklist always fits;
- anything that still doesn't fit is cut at a line break, or named in a closing "Left out" line, with the path of
  the full report, which is always saved to `~/.agents/var/session-start-report.md`;
- the banner is always the first line.

Moving the changing parts to the end would not create cache hits: Claude Code puts this output in the same
message as the working directory and (interactively) the first prompt, and both change every session.

## What's still prose in CLAUDE.md

**Step 12 (auto-route suggestion)** can't move into this hook: it depends on
keyword-matching the user's *first message*, which doesn't exist yet at
`SessionStart` time. That one instruction stays literal in CLAUDE.md.

## Failure isolation

Every check runs through a `_safe()` wrapper — an exception in one check is
logged to `hook-errors.log` via the shared `hook_errors.log_hook_error()` and
treated as "nothing to report," so one broken check can't blank the rest of
the session-start report. Same pattern used elsewhere in MARVIN for hooks
that fail open by design (see `hook_errors.py`'s own docstring).

## Editing this checklist

If you add, remove, or change a check in `session_start_report.py`, update
the table above in the same commit — this doc and the script are two
descriptions of the same behavior, and keeping them in one edit is what
keeps them from drifting apart. There's no automated check that they match.
