# Proposals in MR Review: intent review and mock-up (2026-10-15)

Ticket: G-Eskayo/marvin#102 "Proposals section in MR Review". Decision record: ADR 0068 (PR #535). Supersedes PR #358 "Suggestions tab".

## What we decided

- **Purpose:** big ideas that would make the system better, each tied to a north star, readable by a lay person. Bugs and small fixes are not proposals.
- **Where:** a Proposals section inside MR Review, not a tab of its own.
- **Sources:** the research colony, active projects, architecture-review (big ideas only), and your own "idea: …" in chat.
- **Card:** a title, then Problem / Fix / Why it matters in plain English; size, area and north-star tags; "Technical details" folded away.
- **Actions:** Make it a ticket, Ask MARVIN, Snooze, Dismiss with reason, and Dismiss until X (a ticket that's done, or something you describe, plus a backup date).
- **The old backlog:** all 61 pending entries in suggestions.md were small fixes. They're now tickets #470–#530, so Proposals starts empty.

## Before: PR #358 (sent back twice)

![PR #358 list](docs/screenshots/102-before-suggestions-list.png)

![PR #358 detail: raw engineering text](docs/screenshots/102-before-suggestion-detail.png)

## Mock-up, captured from the real dashboard

The three ideas below are **made-up samples** to show the format; they aren't real proposals. The styling is the dashboard's existing look, with nothing restyled.

**1. MR Review → Proposals.** A third button next to Open | Merged.

![Proposals list](docs/screenshots/102-proposals-mock-list.png)

**2. Dismiss menu**, with Technical details opened on the first card.

![Dismiss menu](docs/screenshots/102-proposals-mock-menu.png)

**3. Dismiss until…** Pick a ticket that has to be done (or create one), or describe something MARVIN checks for each week. A backup date always applies.

![Dismiss until dialog](docs/screenshots/102-proposals-mock-until.png)

## Open questions for you

1. Does the card read right, or is it too long? (An alternative is title + "Why it matters" only, with the rest shown when you open it.)
2. Placement: a third toggle as shown, below the open PRs, or a toggle plus a dot on the MR Review tab when something new arrives?
3. Any actions to rename, move or drop?

## Follow-up tickets

#531 "Proposals store", #532 "architecture-review: file small fixes as tickets, send only big ideas to Proposals", #533 "Feed Proposals from research colony, active projects, and Gil's chat ideas", #534 "Bring back proposals dismissed 'until X'".
