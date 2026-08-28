# 0027 — qa-agent gains a blocking, LLM-judged merge-time role

## Status

Accepted (2026-08-28)

## Context

[[0026]] added `code-review` as a blocking merge-time gate (diff-local correctness/quality).
Separately, Gil wants a check for something `code-review` doesn't cover: whether merging a ticket
leaves MARVIN *net worse off as a system*, even when the ticket's own tests pass and its diff looks
locally clean — plus surfacing improvements to the wider system the ticket's own scope wouldn't
otherwise touch.

`qa-agent` (`~/.agents/skills/qa-agent/`) as it exists today is pure scan-and-query: it extracts
patterns (stack, deps, TODO/FIXME/HACK markers) into a ChromaDB knowledge base tagged by category
(`pattern`/`anti-pattern`/`failed`/etc.) and answers similarity queries against it. It has no
judgment capability — it cannot today assess whether a change is a net negative.

Two shapes considered for closing this gap:
- **(a) Mechanical**: reuse the KB's existing anti-pattern/failed taxonomy as a diff-vs-baseline
  scan comparison — block only if the diff introduces something already tagged bad elsewhere in
  the KB. Buildable with existing qa-agent capability, no new judgment needed, but can only catch
  *known*-bad patterns repeating, not evaluate net system impact or propose improvements.
- **(b) Judged**: an LLM pass at merge time, informed by KB context retrieved across *all* domains
  (not just this ticket's), that reasons about the change's system-wide impact and can propose
  improvements — genuinely new capability, not just a new call site for what exists.

## Decision

**(b), with (a) explicitly staged as a future cheaper upgrade/precursor**, not the destination.
qa-agent's merge-time role: retrieve relevant KB context (this domain and laterally across others,
reusing the already-built `--lateral` query mode) for the ticket's diff, then run a judged pass
assessing whether merging leaves the system net worse off absent further changes, and surfacing
system-wide improvement suggestions the ticket's own scope doesn't require. It blocks the merge
only when it judges a genuine net-negative outcome without those improvements — not on every
suggestion, which would make it a nag rather than a gate.

## Consequences

- Reuses the KB's existing category taxonomy and lateral-query mode as retrieval context, but the
  judgment/blocking layer itself is new build, not composition of what's shipped today — sized
  more like a second `code-review`-class pass than a qa-agent extension.
- Two independent blocking gates now sit in the merge path ([[0026]]'s rebase+retest,
  `code-review`, and this) — failure-routing (which `needs-reengagement` category each maps to,
  see ADR 0025's four reasons) is not yet resolved; a diff-local `code-review` finding and a
  system-wide qa-agent block likely need different re-engagement handling and aren't the same kind
  of "regression/quality" feedback.
- (a) is deliberately not built now — staged as the fallback if (b)'s judgment quality/cost doesn't
  hold up in practice, or as a cheap pre-filter in front of (b) later. Not designed further here.
- Scope/cost of a full-system judged pass per merge is unbounded until qa-agent's actual prompt and
  retrieval breadth are designed — that design work is not done by this ADR, only the shape.
