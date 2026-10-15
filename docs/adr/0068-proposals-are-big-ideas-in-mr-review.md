# 0068 — Proposals: big north-star ideas, in MR Review, written for a lay reader

## Status

Accepted (2026-10-15)

## Context

Ticket #102 asked for a read-only Suggestions tab that renders `~/.claude/suggestions.md`. Its pipeline build, PR
#358, failed automated checks 119 times and Gil sent it back twice (2026-10-10, 2026-10-13): the content wasn't
readable by a lay person, nothing on it could be acted on, and it might belong inside another tab. The PR showed
each entry's raw engineering note: one paragraph of file and function names.

On 2026-10-15 we reviewed the intent with Gil. The feature is meant for **big ideas**: changes that would make the
system better in line with a north star ([`docs/north-stars.md`](../north-stars.md)), drawn from the research colony
and the projects Gil is working on. Bugs and small fixes don't belong in it. The same day, a read of
`suggestions.md` found that all 70 entries were small fixes, with no big ideas. The architecture-review output had
also gone 46 days without being consumed. So the problem was the feed as much as the view.

Alternatives considered: its own tab (what was built; Gil asked whether it belonged elsewhere); a section in Health
(it is MARVIN diagnosing itself, but ideas aren't health); no UI at all, auto-promoting the top items to tickets
(nowhere to read or weigh an idea).

## Decision

- **Where:** a **Proposals** section inside MR Review, next to the PRs. Weighing an idea and approving a PR are the
  same kind of decision, made in the same place.
- **What counts:** a proposal is a big idea tied to a named north star. Small fixes and bugs go to the fix pipeline
  as needs-triage tickets (or auto-fix), never into Proposals. The 61 pending fixes were filed as tickets
  G-Eskayo/marvin#470–#530 and marked `ticketed` in `suggestions.md`. Proposals starts empty.
- **Sources:** the research colony; active projects (handoffs, roadmap, open tickets); architecture-review, limited
  to system-level ideas (new capability, big simplification), with its small findings filed as tickets directly;
  and Gil's own "idea: …" in chat.
- **How one reads:** a card with three plain-English lines (**Problem**, **Fix**, **Why it matters**), a size tag, an
  area tag and the north star it serves. The original technical text is folded under "Technical details". The plain
  lines are written once, when the proposal is added, not at render time.
- **Actions:** Make it a ticket, Snooze, Ask MARVIN about it, Dismiss with a reason, and **Dismiss until X**. For
  "until X", Gil either links a ticket (if none exists for X, one is created; the proposal returns when that ticket
  closes, which code checks) or describes X in words (MARVIN judges on each pass whether X exists yet). Either way a
  backup date always applies, so nothing is buried for good.

## Consequences

- PR #358 is superseded and closed. Ticket #102 stays held and is built with Gil interactively, starting from an
  in-app mock-up.
- A dismissed proposal records why, so the sources stop re-suggesting it.
- "Until X" described in words relies on a model's judgment and can misfire in either direction. The backup date
  bounds the cost of a miss, and the ticket-linked form is the checked path.
- Architecture-review's output gets a consumer again: big ideas reach Gil through Proposals and fixes go through
  tickets. Both answer the 30-day cut rule.
- Every source has to write the plain Problem/Fix/Why lines, which means a model call when an idea is added rather
  than when it's viewed.
