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
| 1 | Handoff | `~/.claude/handoffs/*.md` | Full text of the most recent handoff, if ≤7 days old |
| 2 | Suggestions | `~/.claude/suggestions.md` | Count of `**Status**: pending` entries |
| 3 | Lexicon | `~/.claude/lexicon.md` | Full contents, always loaded |
| 4 | Improvement queue | `~/.claude/improvement-queue.md` | Count of queued `- **[...]**` items |
| 5 | Quarantine | `~/.claude/quarantine.md` | Runs `process_quarantine_reviews.process()` first (feeds checked approve/deny/modify boxes into calibration), then counts remaining unresolved entries |
| 6 | Hook errors | `~/.claude/logs/hook-errors.log` | Count of entries in the last 24h |
| 7 | Cron health | `~/.claude/logs/cron-health.md` | Contents of the "## Latest" block, unless it says "All monitored jobs ran cleanly." |
| 8 | Auto-fix log | `~/.claude/auto-fix-log.md` | Most recent entry, if within the last 24h |
| 9 | Sync log + git conflicts | `~/.claude/sync-log.md` (informational only) + live `git status`/`git stash list` on `~/.claude` and `~/.agents` (authoritative) | Latest sync-log activity, plus **live** conflict/stash state — deliberately NOT decided by scanning log text for the word "CONFLICT", because a resolved conflict's log line stays inside the 24h window and would falsely keep flagging as open. See the docstring on `check_git_conflicts()` for why. |
| 10 | Daily digest | `~/.claude/daily-digest/<today>.md` | Whether today's digest exists |
| 11 | Research digest | `~/.claude/research-digest/<today>.md` | Whether today's digest exists, plus item/correlation counts |

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
