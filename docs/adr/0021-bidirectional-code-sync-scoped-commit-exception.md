# 0021 — Bidirectional code sync via a scoped auto-commit exception

## Status

Accepted (2026-07-09)

## Context

Fixing MacBook Pro's `~/.agents` (it was never a real git clone — a stale manual copy from
2026-07-02, split further by a second, half-current clone at `~/marvin` that only one launchd
plist knew about) closed today's immediate gap but left the actual problem unsolved: nothing
keeps the two machines' code in sync going forward, so the same drift starts recurring the moment
either machine's `~/.agents` changes again.

Several genuinely open alternatives were weighed:

- **Single-writer vs. bidirectional.** Mirroring `cross_machine_merge.py`'s fixed merge-authority
  pattern (always the stationary machine) was the initial recommendation — it sidesteps conflict
  handling entirely. Rejected: Gil's actual goal is "work on either machine, it doesn't matter
  which" (the "one computer, two machines" north star) — most work happening on the Mac Mini today
  is a current-state artifact, not a design constraint.
- **Manual-only vs. a scoped auto-commit exception.** `CLAUDE.md`'s Git Safety Protocol is explicit
  and repeated: "NEVER commit changes unless the user explicitly asks... it is VERY IMPORTANT to
  only commit when explicitly asked." Keeping commits manual (only automating pull/fetch) would
  respect that rule without modification, at the cost of solving only half the drift problem —
  pushing still depends on remembering to ask. Gil chose the exception explicitly, scoped narrowly
  to this one repo, conditioned on genuine transparency (not a silent loosening of the rule
  elsewhere).
- **Build a conflict-resolution tool vs. fail loud + live repair.** `auto_fix.py` was considered as
  a base to extend, but its safety review scoped it to NAMING/VERBOSITY cosmetic findings only —
  extending it to arbitrary git conflicts would exceed what it was reviewed for. Building a new
  dedicated resolver was rejected as designing for a hypothetical before a single real conflict has
  been observed (the composability/KISS principle already applied elsewhere this session). Landed
  on: auto-merge non-overlapping changes (git's own merge machinery handles this natively), and for
  genuine conflicts, fail loud into the same transparency log, resolved by a normal live session
  noticing it and fixing it — the same way manual resolution already works today, just surfaced
  automatically instead of requiring Gil to notice the drift himself.
- **Unify with `cross_machine_merge.py` vs. keep code sync and data sync fully separate.**
  Considered reusing the existing SSH-transfer infrastructure. Rejected: the two solve structurally
  different problems — code sync wants one canonical state (git's actual job), data sync wants a
  *union* of independent findings across machines (explicitly not overwriting). Forcing one
  mechanism to do both would fit neither well. The only shared surface is the transparency
  *pattern* (both log somewhere checked at session start), not the transport.

## Decision

Code sync (`~/.agents` only) is bidirectional and git-based: either machine may auto-commit and
push, and either may auto-pull. Auto-commit+push fires from `handoff`'s existing PostToolUse hook
(session/topic-switch moments) plus a daily launchd cron backstop for sessions that never trigger a
handoff. Auto-pull fires at session start on each machine. A machine with uncommitted local WIP at
pull time gets a stash → pull → pop, not a skip. Non-overlapping changes auto-merge; genuine
conflicts fail loud rather than attempting automated resolution. Every auto-commit, push, and pull
writes to `~/.claude/sync-log.md`, checked at session start — mirroring `auto-fix-log.md`'s existing
"autonomous but never silent" pattern.

This is a **scoped exception** to `CLAUDE.md`'s standing "never commit without being asked" rule,
limited to `~/.agents` specifically, made in exchange for real transparency (the sync-log, not just
a promise) — not a general loosening of that rule for any other repo or purpose.

## Consequences

Solves the actual recurring-drift problem (today's fix was one-time; this is the mechanism that
keeps it fixed) and matches the stated goal of working from either machine without friction.

Known gaps this doesn't resolve: no conflict-resolution tooling exists yet — the first genuine
merge conflict will be resolved by hand, by whichever live session notices the `sync-log.md` entry,
until (if) that becomes common enough to justify automating (deliberately not built ahead of a real
case). Push races (both machines auto-pushing around the same time) aren't explicitly designed for
here — the pull-before-commit/stash-pop flow should make a losing push just fail and retry after a
pull, but this hasn't been verified against a real simultaneous-session scenario. Also out of scope
here, flagged as a separate future idea, not decided: whether MARVIN should eventually run inside a
container to eliminate the class of problem that motivated today's earlier fix (Homebrew's
`python3.11`/`python3.14` having a broken `libexpat` link on MacBook Pro specifically) — a materially
bigger architectural question than this ADR, deserving its own `grill-with-docs` pass, and
complicated by pieces like `DesktopLive.app` (a native macOS app) that can't be containerized at
all.