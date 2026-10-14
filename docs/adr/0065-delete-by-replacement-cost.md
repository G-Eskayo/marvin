# ADR 0065 — Delete by replacement cost

**Date:** 2026-10-14  
**Status:** Accepted  
**Related:** ADR 0056 (disk ledger, auto-trim), storage plan §9 (`docs/plans/storage-and-distribution-2026-10-06.md`)

## Context

The rule so far was "nothing is deleted without Gil's approval for that specific item". That put the gate in the wrong place. A builder simulator (`Seal-118`, 3.5 GB) kept running for four days after its ticket merged. Removing it needed no judgment, yet nothing removed it, because cleanup depended on a line in the builder prompt and on approval. Meanwhile the nightly trim was only allowed to touch small caches.

Gil's framing (2026-10-14): whether something can be deleted comes from "is this important", and that means how hard and slow it is to replace. If something can be spun back up straight away and pick up where it left off, it should be cleaned up as part of finishing the work.

## Decision

Every deletion decision comes from the item's **replacement cost**. There are three tiers:

| Tier | Test | Examples | Rule |
|---|---|---|---|
| **Disposable** | Recreated in seconds to minutes, and everything worth keeping is already saved elsewhere (committed, pushed, in the PR) | builder simulators, build output, worktrees whose PR merged or closed, npm/pip/SwiftPM caches | Cleaned up **as part of finishing the work**, with no approval. Leaving it behind is a bug, and the nightly sweep is only a safety net. |
| **Costly** | Comes back intact, but slowly or with a big download | Ollama models, simulator runtimes, desktop-app VM bundles, aerial wallpapers | Removed automatically **only when the disk is short of space** (ADR 0056 threshold), with a log line saying how to get it back. Prefer things nobody has used recently. |
| **Irreplaceable** | Holds something that exists nowhere else | uncommitted or unpushed work, Gil's files, logs and history, transcripts, worktrees with no PR | **Never deleted automatically.** Gil approves each item. Lossless compression is allowed. |

If it's unclear which tier something is in, it's treated as the more protected tier. Before deleting anything disposable, its saved-elsewhere condition is checked (for example the PR is merged, or `_preserve_prior_attempt` has run), not assumed.

## Consequences

- Anything that creates a disposable resource also removes it when the run ends, pass or fail: simulators the same way as `drop_build_output` (C3).
- `disk_trim`'s allowlist can grow into the costly tier, still behind the low-space threshold.
- The "per-item approval" rule now applies only to irreplaceable items.
