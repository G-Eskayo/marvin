# 0017 — suggestions.md: priority-ordered backlog, whole-system scope, not TaskList-backed

## Status

Accepted (2026-07-09)

## Context

`suggestions.md` had been empty since its creation — `architecture-review`'s own trigger ("every
3-5 sessions") was pure prose with no actual mechanism counting sessions or firing anything (the
exact same bug shape as ADR 0015's `calibrate.py` finding). Before fixing the trigger, Gil asked a
more fundamental question: what does this file actually do, is its scope still right, and — since
he described it as "a dictionary similar to the todo list that can be reordered" — could it be
backed by the platform's own task tools (`TaskCreate`/`TaskUpdate`/`TaskList`) rather than a
bespoke markdown format.

**Checked directly rather than assumed.** `TaskList` returned empty despite 6 tasks created and
completed earlier the same day. Traced the actual storage: `~/.claude/tasks/<session-id>/`, one
directory per session ID, containing only a lock file and a watermark — no durable cross-session
task data. Confirmed definitively: these tools are scoped to the current session, not a backlog
meant to persist across weeks. Ruled out as a backing store for this reason alone.

## Decision

Redesigned `suggestions.md` as a **priority-ordered, reorderable markdown backlog**, not a
chronological log:

- Each entry gets an explicit `**Priority**` field, scored with the same compounding-leverage lens
  used everywhere else in the system (does this unlock/cheapen multiple future items, not just its
  own standalone value).
- `~/.agents/skills/architecture-review/scripts/sort_suggestions.py` physically re-sorts the file
  by priority (ties broken by Impact, then Effort) whenever an entry is added or reprioritized —
  the actual mechanism behind "reorderable," not just a documented convention.
- `architecture-review`'s scope expanded from a named subset (CLAUDE.md, lexicon, skills, commands,
  one script) to genuinely whole-system — everything under `~/.agents` and `~/.claude`, confirmed
  still north-star relevant (its own stated focus — token reduction, retrieval speed — is close to
  verbatim the roadmap's own north-star language) and now doubly relevant since the `audit` skill
  (ADR 0016) also routes its judgment-requiring findings here.
- Deliberately deferred: the actual trigger automation (size-based instant check, weekly cadence)
  that originally motivated this investigation. Format and scope needed to be right before anything
  writes to the file at scale — Gil's explicit sequencing ("tie in later to our self-improving
  automation agents").

**A second, smaller finding surfaced mid-build**: `sort_suggestions.py`'s priority-ranking logic
(map a category to a rank via a fixed list, sort by it) is the same *shape* as
`improvement_sweep.py`'s existing `sort_key()` — different data (a parsed markdown file vs.
ChromaDB dict entries), so not literal duplication, but a duplicated pattern. Gil's direct
question ("don't we already have a sorting tool we could reuse?") is now folded into both
`architecture-review` and `audit`'s own review criteria as a standing check — flag genuine
duplication, don't force-extract a shared utility at just two call sites (logged as its own
low-priority `suggestions.md` entry, dogfooding the exact system this ADR describes).

## Consequences

The trigger-automation work (why this investigation started) is now a clean, well-scoped follow-up
against a format that's actually right, rather than automating writes into a file whose shape was
still wrong. `MIN_LABELS`-style "needs real usage before it's proven" caveat doesn't apply here —
the sort mechanism is deterministic and already verified against real content, not waiting on
accumulated data the way ADR 0015's calibration was.
