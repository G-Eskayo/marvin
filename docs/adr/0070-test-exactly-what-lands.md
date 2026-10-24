# ADR 0070: Test exactly what lands, land only what was tested; a red main queues

**Status:** Proposed (draft, 2026-10-21). Gil approved the direction on 2026-10-21; this ADR becomes Accepted when Gil
approves the design in `docs/plans/merge-system-2026-10-21.md`. **Amends ADR 0061**: replaces its at-Approve overlap
rule and its main-health backstop sentence. Touches ADR 0064 (auto-merge on a red main) and ADR 0069 (who may push to
main).

## Context

ADR 0061 made Approve fast by retesting only when main had changed a file the PR also changes, and named main-health
as the backstop that "refuses merges while main is red". On 2026-10-21 this went wrong in three ways:

- **A cross-file break slipped through.** #557 and #559 shared no file. #559's new repo-wide polling guard rejected
  code #557 had added, and main went red after #559 landed. ADR 0061 accepted this risk as rare. It happened on a
  normal day.
- **The backstop didn't exist.** No code refuses a human Approve while main is red. #569 merged onto a red main
  (e5f8122). Merging onto red is in fact needed, because fixes must be able to land, so the ADR's wording was wrong as
  well as unenforced.
- **What was tested wasn't what landed.** The gate rebases and force-pushes the PR branch, tests it, then
  `gh pr merge --merge` merges onto main *as it is at that moment*. If anything lands in between, main gets a tree
  nobody tested.

GitHub's merge queue would solve the last point, but it's available only to organization-owned public repos or
Enterprise Cloud, and `G-Eskayo/marvin` is user-owned. It would also need self-hosted runners and wouldn't
pre-verify (see the plan, section 2).

## Decision

1. **A test result belongs to a tree.** The candidate for a PR is the merge commit that would land: parents (main *M*,
   PR head *H*), tree *T* = merge(*M*, *H*) + version bump. Verdicts are keyed by `(T, suite fingerprint)` and reused
   whenever the same tree comes up again.
2. **Every merge is tested exactly**, so there's no overlap heuristic. The cost is moved off the Approve path by
   verifying candidates in the background at low OS priority (`taskpolicy -b`) while PRs wait for review. Triggers
   only, never timers: PR head changed, main moved, Approve, service start, suite fingerprint changed.
3. **Land only the tested commit, and only if main hasn't moved:** a plain (non-force) push of *C* to `main`. The
   ruleset's `non_fast_forward` rule makes git accept it only while main is still *M*. If the push is rejected, the
   PR is re-verified against the new main and landing is retried. The merge owner pushes with the same admin bypass
   code-sync uses (**extends ADR 0069's bypass to the merge owner**). Fallback, if Gil prefers to keep merges inside
   GitHub's API: merge with `sha=H` right after confirming main is *M*, then compare trees and flag any mismatch as
   *landed untested*. The commit carries a `Verified-Tree: <T>` trailer.
4. **A red main queues; it doesn't block.** Approve always enqueues. Queued PRs whose failures are a subset of main's
   are *blocked by main* and aren't sent back. The first candidate that passes completely lands, even ahead of earlier
   entries (passing on a red main means it fixes main). Main-health runs only for trees nobody verified (auto-sync code
   commits, merges on GitHub's site, environment changes). Exactly **one** push per red episode, naming the commit or
   commits since the last green tree, sent only by the merge owner through MARVIN's own delivery path (ADR 0046), with
   desktop notification as the fallback.
5. **One queue and one merge owner per repo**, saved on disk (journal + OS file lock) under a MARVIN-owned directory,
   not `~/.claude`. Approves from any device are enqueued idempotently by (repo, PR, head). This supersedes #231.

Unchanged from ADR 0061: after a merge, open PRs are conflict-checked with `git merge-tree` (now as part of building
candidates), with no checkout and no push to the PR branches.

## Consequences

- Main can't go red from a merge through the queue. It can still go red from writers outside the queue
  (code-sync code commits, GitHub-UI merges, environment changes); those are verified at normal priority and reported
  once.
- When the verdict is ready, Approve takes seconds: one PR read and one push. When it isn't, Approve waits for one
  verification of the exact candidate, not a rebase plus a full suite on a branch that may not be what lands.
- One commit per merge instead of two (the version bump lands inside the merge).
- More CPU is spent speculatively, on PRs that may never be approved (historically about 95 % are). Main-health's
  per-merge full runs (estimated 3.6–4.7 h/day of M4 time on 10-21) go away. Net is expected to fall, and the verdict
  store measures it.
- Contributors' PR branches are never force-pushed by the gate.
- The merge owner's direct push depends on the admin bypass. Removing that bypass would require the fallback in
  decision 3.
- ADR 0064's "a red main pauses all auto-merging" becomes: auto entries keep waiting on a red main, and only a
  human-approved candidate may jump the queue as the fix (pending Gil's answer to `auto-fix-jump`).

## Alternatives considered

- **Keep ADR 0061 and add guard tests at Approve (R-P7).** This is cheaper and catches the #557/#559 class only for
  tests tagged as guards. The design supersedes it: exact testing catches every class, and pre-verification hides the
  cost.
- **GitHub merge queue.** Not available for a user-owned repo. Transferring to an organization costs 691 references and
  self-hosted runners, and it still doesn't pre-verify or survive a GitHub outage.
- **Retest every behind PR at Approve** (ADR 0061's "one line away"). It's exact only if nothing lands between the
  test and the merge, and it puts minutes back on every Approve.
- **Blue/green on the same TCP port.** Impossible on macOS with Node: `reusePort` returns `ENOTSUP`. Replaced by a
  durable queue where accepting is separate from executing, a drain, and a client retry across a gap of about 1 s.
