# 0016 — Intent-vs-reality audit agent: reuse the Agent tool, don't build dedicated infrastructure

## Status

Accepted (2026-07-09)

## Context

Grew directly out of the same-day quarantine investigation (ADR 0015): Gil asked whether a
"better investigative agent" would help — one that, when something seems off, compares what the
system's documentation says it should be doing against what it's actually doing, the same move
that surfaced `calibrate.py`'s dead `record_label()` feedback loop. That comparison is genuinely
different from `diagnose`, which requires a known symptom to root-cause; this starts from
documented *intent* (docstrings, ADRs, roadmap markers) with no symptom yet in hand.

Two real implementation shapes were considered.

**Dedicated infrastructure**, mirroring `background_review.py`: a standalone detached `claude -p`
script, its own tool-restriction design (`--tools`, `--permission-mode bypassPermissions`), its
own log file. More control over exactly how it runs, at the cost of a new script + new safety
design to build and maintain — largely re-deriving something the platform already provides.

**Reuse the `Agent` tool's `run_in_background` mode.** Already provides backgrounding, its own
tool-access/safety model, and a notify-on-completion mechanism — exactly the shape Gil described
("reactive... background thing"). Building this as a new *skill* (trigger conditions + an
investigation prompt template) rather than new code is a direct instance of the day's own
compounding-leverage principle: reuse what unlocks this cheaply rather than build a parallel
system.

## Decision

Built as a skill, not a script. Scope, resolved through the same interview pattern as task-dispatch
and mode 2 earlier the same day:

- **Trigger**: reactive, judged by the main conversation agent in the moment — not scheduled, not
  requiring Gil to name a component. Concrete heuristics: a direct verification/status question
  that can't be confidently answered from what's already known; a noticed mismatch between
  documented intent just read and observed system state; Gil expressing suspicion something isn't
  working as documented.
- **Fix authority**: allowed to apply low-risk fixes, but *only* by reusing `auto_fix.py`'s
  existing safety-netted mechanism (narrow category whitelist, core-file exclusion, backup-and-
  revert-on-compile-failure) — not new fix-application logic. The agent's actual job is discovery
  and classification, not fixing.
- **Output routing, by risk tier, no new dedicated file**: fixes applied through `auto_fix.py` log
  to `auto-fix-log.md` same as any other auto-fix. Findings that need real judgment (the shape of
  fix ADR 0015 required — genuine design decisions, not mechanical pattern-matching) go to
  `suggestions.md`, unimplemented, for review — reusing `architecture-review`'s existing queue
  rather than fragmenting output across another file to remember to check.

## Consequences

Not yet built — this ADR captures the resolved scope; implementation (the skill file itself, the
investigation prompt template, refining the trigger heuristics with real use) is the next step,
deliberately sequenced after this session's other work rather than started same-day alongside it.
