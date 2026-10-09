# ADR 0061: After a merge, check; at Approve, retest only when main changed the PR's files

**Status:** Accepted (2026-10-09, Gil: "Does it always need to be rebased if it isn't touching the same files?").
Supersedes the rebase-all part of #225 (CONTEXT.md, 2026-10-07).

## Context

After every merge the webhook rebased every other open PR onto main, ran the full test suite on each, one at a time,
and force-pushed it. With ~8 open PRs that was ~8 suite runs per merge, each made stale by the next merge, plus a
push per PR that re-triggered main-health and GitHub reads. It also never ran in production until 2026-10-09: the
webhook's default exec returned no output, so the step failed on its first line on every merge, silently.

## Decision

- After a merge: move stacked PRs onto the base, then conflict-check each open PR with `git merge-tree --write-tree`
  (no checkout, no tests, no push). Conflicts show on MR Review and the ticket timeline.
- At Approve: a PR behind main is rebased and retested only when main changed, since the two split, a file the PR also
  changes. Otherwise it merges directly. If the overlap can't be computed, it is retested.
- main-health (re-runs the suite on every main move; merges are refused while main is red) is the backstop for the
  rare break between different files (one PR renames what another calls).

## Consequences

- Approve takes seconds for most PRs; suite runs drop from N per merge to one per overlapping Approve.
- A cross-file semantic break can land on main and is caught minutes later rather than before merging. Gil accepted
  that trade; the alternative (retest every behind PR at Approve) stays one line away in `defaultShouldGateMerge`.
