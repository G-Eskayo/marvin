# ADR 0084: An unchanged reading moves on when the build made a real change

**Status:** Accepted (2026-11-06, Gil, option A of three). Ticket #1157.

## Context

Pipeline verify compared test counts before and after a build, and "unchanged" never passed. That failed legitimate work: docs and config tickets, and bug fixes that edit an existing test, where the counts stay the same. Untested code didn't need this rule to stop it: ADR 0063 gate 2 already refuses code that changed with no test change.

## Decision

`metrics_registry.compare()` keeps its meaning. In `execute_ticket`, an "unchanged" reading becomes one of two things:

- **"changed, tests steady"** when the tree holds a real change. It goes on to the test-change rule, code review and Approve, like any other pass.
- **"nothing changed"** when it doesn't. The build fails and the builder is told why.

**A real change** is a file that differs from the base and isn't the ticket's own plan or task list, generated output, a pure rename or blank lines. In code and tests it must be more than comments. In docs and config a line starting `#` is content.

**Stays "unchanged" and fails:** a comparison with no metric on both sides, a build broken before and after (`*build_ok` at 0), and a tree git can't read.

## Consequences

- A test that already fails on the base doesn't block a build on an unchanged reading: the build didn't cause it.
- A tracked binary edited in place has no text lines, so it doesn't count as a real change on its own. It fails closed.
- Tickets whose work happens on another branch, such as "Act on owner decisions", still read "nothing changed" unless they change this tree.
