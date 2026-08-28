# 0026 — Concurrent ticket dispatch, with integration safety moved to merge time

## Status

Accepted (2026-08-28)

## Context

Rewiring `ticket_pipeline.py` to actually drive `sandbox_orchestration.execute_ticket` +
`mr_raiser.py` (see CONTEXT.md's "MR pipeline" section) raised a question neither module had
answered: once multiple tickets can be in flight at once (each isolated in its own git worktree,
each machine freeing up once a PR is *opened*, not once it's merged — see [[0013]]'s single-target
dispatch primitive), what stops them from merging out of order and breaking each other?

Two alternatives considered:
1. **Serialize dispatch** — don't start ticket B until ticket A's PR is merged. Simple, but throws
   away the entire point of running two machines in parallel ([[0013]]'s stated goal), and Gil's
   own framing ("the order things get *integrated*") pointed at the merge step, not dispatch.
2. **Concurrent dispatch, smart merge** — let tickets run in parallel as today's architecture
   already allows; move the safety check to the point where it actually matters, merge time.

## Decision

Dispatch stays concurrent — no throttling added. `merge.js`'s `mergePr` (today: a blind `gh pr
merge`) gains a pre-merge check: if the PR's branch is behind `main`, rebase it onto `main` inside
that ticket's worktree and re-run its test suite before completing the merge. If the rebase or the
re-run fails, the merge is refused and the ticket is routed into the **same** `needs-reengagement`
path issue #72 already designed for a human "deny" (structured feedback comment, label, claim
released) — a merge-time integration failure re-enters the existing re-engagement flow rather than
inventing a new state.

## Consequences

- Reuses `needs-reengagement` for two different failure origins (human deny vs. merge-time
  integration failure) — the re-engagement consumer (issue #73, itself still undesigned) will need
  to be able to tell these apart if the response should differ; not resolved here.
- A rebase-then-retest step means merge is no longer instant/synchronous from the dashboard's
  "click approve" interaction — the webhook's response time and failure modes both change from
  today's shipped approve flow (#11). UX consequence not yet designed.
- Does not resolve how *concurrent, non-conflicting-but-semantically-overlapping* changes (no git
  conflict, but both touch the same subsystem in ways that interact) get caught — a clean rebase +
  passing tests is not proof of semantic safety, only of syntactic compatibility. Open gap.
