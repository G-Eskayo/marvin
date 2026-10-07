# 0054 — Bugs before features

## Status

Accepted (2026-10-07). Adjusts ADR 0047.

## Context

Gil (2026-10-07): "Bugs are a big deal and I would like everything working, which we are not there yet." Dispatch
ordered ready tickets by priority label → urgency score → age (ADR 0047). The `bug` label added only +4 to the score,
less than unblocking two tickets (+6), so a bare bug scored `priority:p2`, the same tier as ordinary features. The
`priority:pN` label is the first sort key, but most ready tickets carry none, so all unlabelled tickets fell into one
"unscored = middle" tier and were sorted by score alone.

## Decision

- **Bug weight +10** (`ticket_policy.BUG_WEIGHT`): a bug on its own scores `priority:p1`. Ordinary features stay p2/p3.
- **Tier first, then bugs.** Dispatch's order key is: priority tier → labelled before score-derived → bug before
  non-bug → score → age. An unlabelled ticket's tier is the one its score earns (`priority_for`, the mapping the
  prioritizer labels with), not a flat "middle".
- **Deadlines keep the final fortnight.** A hard deadline within 14 days scores p0 and goes ahead of bugs. One 15–30
  days out scores p1, the same tier as a bug, where the bug goes first. This replaces ADR 0047's "a hard deadline
  19 days out outweighs a bug that unblocks two": under 0047 deadline work led from weeks out; now bugs lead until the
  last two weeks.
- A priority label someone set still wins (`p0` stays the escape hatch), and a labelled ticket goes ahead of an
  unlabelled one that scores the same tier.

## Consequences

- Bugs anywhere jump ahead of most feature work immediately: dispatch scores live, no relabelling needed.
- clarity-captions' hard deadline (2026-10-25) work yields to bugs until 2026-10-11, then leads.
- This only works if broken behaviour is labelled `bug`. Several were filed as `enhancement` this week (e.g. #215), so
  the triage skill now checks it.
