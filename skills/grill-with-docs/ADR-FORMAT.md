# ADR Format

One file per decision, numbered sequentially: `docs/adr/000N-short-title.md`.

```markdown
# 000N — [Decision, stated as a title, not a question]

## Status

Accepted (YYYY-MM-DD)

## Context

What situation forced this decision. What alternatives were considered and why they were
rejected or preferred. Reference other ADRs by number in brackets, e.g. [[0003]], when this
decision builds on or reopens an earlier one.

## Decision

The actual decision, stated plainly. One or two sentences if possible.

## Consequences

What this decision costs or unlocks. Include known risks or gaps this decision doesn't resolve —
an ADR documents a real tradeoff, not a clean win.
```

Only write one when all three are true (per SKILL.md): hard to reverse, surprising without
context, and the result of a real trade-off with genuine alternatives.
