# Sessions know what other sessions are working on — 2026-10-09

Gil: "why are we having so many issues with duplicates? it seems inefficient and non optimized. what can we build to
fix this? where do we start our investigation?" then "write the plan and build it but first check, I thought we
already built this?"

## What already exists (checked 2026-10-09)

- **Pipeline vs pipeline:** ticket claims as GitHub labels (`ticket_claim.py`), the two-machine claim tiebreak
  (`ticket_coordination.py`), parallel-dispatch slots and guard rails (#193–#198), and the double-dispatch fix
  (#255, PR #257). These work: 72 of 75 PRs since 2026-09-25 merged; one ticket (#166) got two pipeline PRs.
- **Hooks:** `lib/marvin_hooks.py` installs MARVIN's hooks at user level on both Macs, gated by launch kind.
  `brain-map/scripts/skill_activity.py` logs every tool call for the map, but only `{skill, ts}`: no session, no files.
- **Not built:** anything that tells an interactive session what ANOTHER session, or the pipeline, is doing.

## What went wrong (the evidence)

On 2026-10-08/09, two interactive sessions on the laptop (two WezTerm tabs) and the mini's pipeline worked the same
problems in parallel, each from Gil's report of the same symptom:

| Problem | Session A | Session B / pipeline |
|---|---|---|
| Tests reaching real GitHub | 850b7d9 | 5e2830f, 14557b5 |
| Stacked PRs reaching main | 85a5436 | d0b19d5 (#317) |
| Dashboard GitHub load | 7210d6a (#318), c3446ce | def5245 (#323/#324) |
| Merge server restart after merge | by hand | 5a9c278 |
| Ticket #318 | built directly on main | pipeline built PR #319 (closed as duplicate) |

Root cause: nothing records "I am working on this" where the others look. Interactive sessions don't claim tickets,
many fixes start with no ticket, and two tabs on one Mac can't see each other's edits until auto-sync commits them.

## Decision (ADR 0062)

1. **A live "working on" list per Mac** (`lib/session_work.py`, `~/.claude/logs/sessions-active.json`). Hooks keep it
   current: each session's latest request (UserPromptSubmit) and the files it edits (PostToolUse Edit/Write), keyed by
   repo + path so a worktree copy and the shared checkout count as the same file. An entry is live while the session
   was active in the last 45 minutes.
2. **An overlap check before editing** (PreToolUse Edit/Write, interactive sessions). If another live session on
   this Mac edited the same file, the edit pauses and asks Gil, naming the other session's request and when it last
   touched the file. Asked once per file per pair of sessions; after that it goes through.
3. **Claim before building.** When an interactive session first edits a repo and its latest request names exactly one
   open `ready-for-agent` ticket of that repo with no claim, the ticket gets `claimed:<this Mac>` (in the background),
   so the pipeline skips it. That is what would have prevented #319.
4. **MR Review notes a PR whose ticket is already closed** ("probably superseded"), so a stale duplicate is obvious.

Out of scope for now: sessions on the other Mac (the list is per Mac; the pipeline is covered by claims), and merging
#257 (Gil's call; it fixes pipeline double dispatch).

## Tasks

One ticket, built in-session and claimed: the list + hooks (1, 2), auto-claim (3), MR Review note (4), installed
on both Macs through `marvin_hooks.py install`.
