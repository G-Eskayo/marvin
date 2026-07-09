---
name: audit
description: Reactive background investigation comparing documented intent (docstrings, ADRs, roadmap markers) against actual system state to find gaps nobody's reported yet. Distinct from diagnose, which needs a known symptom to root-cause. Trigger when a direct verification question can't be confidently answered, a mismatch is noticed between something just read and observed state, or Gil expresses suspicion something isn't working as documented. Dispatched via the Agent tool in background mode — not standalone infrastructure.
tags: [intent:investigate, intent:audit, intent:meta, domain:reliability, type:skill]
---

# Audit

Grew out of the 2026-07-09 quarantine investigation (`~/.agents/docs/adr/0015-quarantine-review-feedback-loop.md`): `calibrate.py`'s own docstring said `record_label()`'s "intended caller" was "the quarantine review workflow, once built" — and nothing had ever built it. That's the shape of gap this skill exists to find: not a reported bug, a **divergence between what the system says about itself and what it actually does**.

Full scope/design rationale: `~/.agents/CONTEXT.md`'s "Intent-vs-reality audit agent" section, `~/.agents/docs/adr/0016-intent-reality-audit-agent-scope.md`.

## When to trigger

Judged in the moment by the main conversation agent — not scheduled, not requiring the user to name a component. Fire on:

- A direct verification/status question ("did X happen?", "is Y actually working?") that can't be confidently answered from what's already in context — the exact moment that started the 07-09 investigation.
- Noticing a mismatch mid-task between something just read (a docstring, an ADR, a roadmap `[decision]`/`[research]` marker, a comment claiming "this is handled by...") and observed system state.
- The user expressing suspicion or asking "what is X supposed to do vs. what does it actually do?"

Don't trigger for: a reported bug with a known symptom (that's `diagnose`), routine "is this file up to date" checks, or anything where the answer is already directly visible without investigation.

## How to dispatch

Use the `Agent` tool with `run_in_background: true` (unless the user is actively blocked waiting on the answer, in which case foreground). Do not build a standalone script for this — the `Agent` tool already provides backgrounding, its own tool-access safety model, and a notify-on-completion mechanism.

Brief the agent like `Agent`'s own guidance demands — a fresh agent, no memory of this conversation:

```
Investigate [component/subsystem name] for gaps between what it's documented to do and
what it actually does. Read: [specific docstrings/files known to describe intent], any ADRs
in ~/.agents/docs/adr/ mentioning it, any ~/.claude/marvin-roadmap.md entries referencing it
(especially [decision]/[research]-tagged ones that may never have been resolved to [done]).
Then check actual state: [specific files/logs/directories that would reveal real behavior] —
does real behavior match what's documented? Look specifically for: functions whose docstrings
describe an "intended caller" or dependency that doesn't exist; roadmap decisions left open
that were silently defaulted one way in practice; comments/docstrings promising a mechanism
elsewhere in the codebase that was never actually built; a new script implementing the same
*shape* of logic as an existing one on different data (a duplicated pattern, not necessarily
copied code — added 2026-07-09, Gil's direction: every new script is something to maintain
going forward, so check for reuse before assuming something new is needed).

For each real divergence found:
- If it's fixable within the exact scope auto_fix.py already covers (NAMING/VERBOSITY
  findings only, files under ~/.agents, never files in auto_fix.py's own _core_files()
  exclusion list) — run auto_fix.py, don't fix it yourself.
- Otherwise, do NOT fix it. Append a suggestion to ~/.claude/suggestions.md using
  architecture-review's exact entry format (## [date] [title], Status: pending, Impact,
  Effort, Why, What, How) so it's queued for review, not silently changed.

Report back: what you found, what you fixed (if anything, via auto_fix.py), what you queued.
```

## Output routing

No new dedicated findings file — reuse what already exists, split by risk tier:

- **Low-risk, auto-fixable** (matches `auto_fix.py`'s existing narrow scope exactly): triggered via `auto_fix.py`, not fixed directly. Lands in `~/.claude/auto-fix-log.md`, same as any other auto-fix run. Session Start step 8 already surfaces this.
- **Needs real judgment** (a design decision, a logic change, anything auto_fix.py's safety boundary doesn't cover — the shape of all three fixes in ADR 0015): appended to `~/.claude/suggestions.md` in `architecture-review`'s exact format, unimplemented, queued for the user's review. Session Start step 2 already surfaces the pending count.

If the investigation finds nothing — intent and reality actually match — don't write anything anywhere. A clean result isn't a finding.

## Reporting back to the user

When the backgrounded agent completes, relay a concise summary in the main conversation — what was investigated, what was found (or that nothing was), what got auto-fixed vs. queued. Don't dump the full investigation transcript; the durable record already lives in `auto-fix-log.md`/`suggestions.md`.
