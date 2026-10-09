# ADR 0063: Tests try to break it, enforced at every gate from idea to running code

**Status:** Accepted (2026-10-09, Gil). North star 4 and the guiding principle "Tests try to break it"
(`docs/north-stars.md`). Designed in the #332 auto-merge session.

## Context

Gil: "Test means trying to break everything in every feasible way possible that a user or system could use or misuse
it and test it behaves appropriately", and it must be enforced by how the system turns ideas into reality, not kept in
memory. For anything outward-facing, that includes attacking it like an adversary. Every bug fixed on 2026-10-08/09 had
happy-path tests and broke on misuse or odd conditions (a mocked stage log hid a rejected status; a hook after an
early return blanked a tab; gh's reason sat on stderr).

## Decision

The principle is enforced at five points:

1. **Ticket.** Every build ticket has a "How we'll try to break it" section: the misuse cases, plus a security part
   when it touches an outward-facing surface. Ticket-writing skills always write it; **triage won't mark a ticket ready
   without it**.
2. **Build.** Pipeline agents write a test for each listed case, first. **Verify fails** when code changed and no test did.
3. **Merge.** A **mutation check** plants small bugs in the PR's changed lines; the PR's tests must catch **≥ 80 %** to
   auto-merge (#332). Below that it still merges with Gil's Approve, and the card names the bugs that survived.
4. **Direct commits.** A commit check refuses code changes without test changes unless the commit states a reason;
   reasons are recorded and shown in Health. (Closes the path around the pipeline: sessions committing to main.)
5. **Trend.** Health/Metrics show mutation scores over time and every merge or commit that skipped breaking-tests.

Outward-facing surfaces (a non-exhaustive start): the portfolio site's forms and text boxes, the merge webhook and
refresh ports, the mobile backend, the dev-site tunnel, the public map, and anything that feeds outside text to a model.

## Consequences

- Tickets take a little longer to write and to build; fewer come back.
- Docs- or config-only changes pass the commit check with a stated reason.
- The gate and the commit check are core (always ask); they can't loosen themselves through auto-merge.
