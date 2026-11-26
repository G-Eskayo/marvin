# ADR 0086: Evidence-only retries keep the worktree

**Date**: 2026-11-26
**Status**: Accepted

## Problem

When a ticket's execute_ticket passes verification (the build is successful) but times out during evidence capture (test results or screenshots), the entire worktree is discarded and the next attempt must rebuild from scratch. This wastes machine time and API tokens.

The timeout occurs during `_raise_with_evidence()` in `run_ticket.py:build()`, specifically in `capture_test_results()` or `capture_dev_evidence()` calls. The build itself succeeded and the code is correct; it's only the evidence reporting that failed due to time constraints.

## Solution

Implement an **evidence-only retry** mechanism that:

1. **Preserves evidence on timeout**: When evidence capture times out, save partial evidence to a `.pending.json` marker file inside the worktree.
2. **Keeps the worktree for retry**: The cleanup sweep detects the pending marker and skips removal, allowing the next dispatch to reuse the same tree.
3. **Reuses cached evidence**: On the next attempt, `build()` detects the pending marker and calls `raise_mr()` directly with the cached evidence, skipping the entire build/execute cycle.
4. **Falls back to full rebuild**: If the pending marker is stale (the result changed between attempts), fall back to a full rebuild.

## Outcomes

### Worktree lifecycle with evidence timeout

```
Attempt 1:
  execute_ticket → PASS
  _raise_with_evidence() starts → capture_test_results() → TIMEOUT
  Write pending marker: {"result": {...}, "test_results": null, "dev_evidence": null}
  outcome = {raised: False, evidence_timed_out: True}
  settle() → release claim, post timeout comment, redispatch

  cleanup_sweep: Detects pending marker → keep worktree

Attempt 2:
  execute_ticket (skipped, worktree already built)
  _resume_pending_evidence() reads marker → found, matches result
  raise_mr(ticket_ref, result, test_results=cached, dev_evidence=cached)
  outcome = {raised: True, pr_url: "..."}
  settle() → recorded as success
  cleanup_sweep: No pending marker → remove worktree as normal
```

### Key components

1. **`evidence_capture.pending_evidence_path()`**: Returns the marker file path.
2. **`evidence_capture.{read,write,clear}_pending_evidence()`**: Marker API with corruption tolerance.
3. **`sandbox_orchestration.worktree_path_for(ticket_ref)`**: Compute worktree path without creating it.
4. **`run_ticket._raise_with_evidence()`**: Extracted evidence capture; writes marker on timeout, re-raises.
5. **`run_ticket._resume_pending_evidence()`**: Read and clear marker; return evidence if result matches.
6. **`run_ticket.build()`**: Try resume before full capture; fall back to `_raise_with_evidence()`.
7. **`run_ticket.settle()`**: New `evidence_timed_out` branch (identical to `timed_out` for retry logic).
8. **`cleanup_sweep.decide_worktree()`**: Early return for pending markers (keep worktree).
9. **`mr_raiser._format_test_results()`**: "couldn't capture" branch for incomplete evidence.

## Decisions

### A: Scratch-ref push on cross-machine retry

**Question**: When a ticket on the Mac mini times out during evidence and must retry on the laptop (or vice versa), should the pending marker be pushed to the remote so the other machine can fetch it?

**Options**:
- **A**: Push to a temporary `scratch/<branch>-<timestamp>` ref on origin; the other machine fetches it and merges into the worktree.
- **B**: No cross-machine transfer; each machine attempts evidence capture independently (may succeed on the second machine).

**Chosen**: **B** (not implemented; keep worktrees machine-local for now).
  - Rationale: Pending markers are local state. Cross-machine retry complexity (fetching, merging, deduping in mr_raiser) outweighs the rare case where machine load differs enough to cause timeout on one but not the other.

### B: Stale marker handling

**Question**: If the pending marker's result dict doesn't match the current result (the compare/verdict changed), should we:

**Options**:
- **B1**: Discard stale evidence and do a full rebuild.
- **B2**: Try to reuse the stale evidence anyway.

**Chosen**: **B1** (implemented in `_resume_pending_evidence()`).
  - Rationale: A stale marker means the ticket was re-dispatched and re-executed. The old evidence is from a different attempt; using it would misrepresent this attempt's true results.

## Tests

- **Tests 1–2**: `_raise_with_evidence()` captures evidence and re-raises on timeout.
- **Tests 3–11**: `_resume_pending_evidence()` reads/clears markers, falls back on stale evidence, integrates into `build()` and `settle()`.
- **Test 4**: `cleanup_sweep.decide_worktree()` keeps worktrees with pending markers.
- **Additional**: Marker API corruption tolerance (tests 7–8).

## Alternatives considered

1. **Extend execute_ticket's timeout retry**: Retry evidence capture inside the same execute_ticket call. Rejected: execute_ticket's loop is for code changes, not for I/O failures on a passing build.
2. **Stash evidence to disk on first pass, retry in second round**: Similar effect but no isolation between attempts; a later round's fresh evidence could overwrite an earlier round's cached state.
3. **MR without evidence**: Raise a PR with no test results or screenshots if capture times out. Rejected: the merge gate requires evidence for UI changes; PRs without it get held or rejected.

## Related

- **ADR 0024**: Evidence schema (test results, dev evidence).
- **ADR 0063**: Tests try to break it; build once, verify via fresh tests.
- **marvin#1152**: Paired measure; baseline captured at the same stage as the change.
