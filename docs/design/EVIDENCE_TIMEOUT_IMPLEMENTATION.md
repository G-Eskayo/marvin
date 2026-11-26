# Evidence Capture Timeout System Implementation

## Overview
This implementation adds resilience for evidence capture timeouts in the ticket pipeline. When evidence capture (screenshots, test results, design docs) times out but the code has already passed verification and been pushed, the PR still opens with partial evidence, and evidence capture is retried on the next dispatch cycle.

## Changes Made

### 1. run_ticket.py
- Added `EVIDENCE_TIMEOUT_MARKER` and `MAX_EVIDENCE_RETRIES` constants
- Updated `_trailing_streaks()` to return 3-tuple: (failures, verify_timeouts, evidence_timeouts)
- Modified `build()` to:
  - Push code immediately after `result["passing"]` via `mr_raiser.push_passing_code()`
  - Write evidence sidecar with partial evidence if capture times out
  - Wrap evidence capture in try/except TestTimedOut
  - Pass branch name in outcome when evidence times out
- Added `evidence_only()` function to retry evidence capture on a pushed branch
- Updated `settle()` to handle `evidence_timed_out` outcome by:
  - Creating evidence_pending marker with branch and retry time
  - Releasing claim and redispatching
  - Parking after MAX_EVIDENCE_RETRIES consecutive timeouts
- Updated `main()` to handle `--evidence-only` flag for evidence retry dispatch
- Added tests for evidence timeout tracking and handling

### 2. mr_raiser.py
- Added `push_passing_code(worktree_path, ticket_ref)` as public wrapper around `_commit_and_push`
- Updated `_format_test_results()` to handle capture_failed key for timeout cases

### 3. sandbox_orchestration.py
- Added `_evidence_sidecar_path()` function to get evidence JSON file path in worktree
- Sidecars store test_results and dev_evidence for evidence-only retries

### 4. ticket_policy.py
- Added `EVIDENCE_PENDING_MARKER` constant and regex pattern
- Added `evidence_pending(comments, now)` function that returns (branch, retry_time) when ready to retry, None otherwise
- Mirrors `retry_not_before()` pattern for time-based retry gating

### 5. ticket_pipeline.py
- Added `_evidence_pending_branch()` to check if ticket has evidence pending
- Updated `_build_wrapper_command()` to accept `evidence_only_branch` parameter for `--evidence-only` dispatch
- Modified `_dispatch_one()` to check evidence_pending status before build dispatch
- Routes evidence-only tickets via modified command line

### 6. cleanup_sweep.py
- Added `_default_evidence_pending()` to check if ticket is pending evidence retry
- Updated `decide_worktree()` to keep worktrees with pending evidence
- Updated `sweep_worktrees()` to track evidence_pending status

### 7. Tests
- Added tests in test_run_ticket.py:
  - evidence timeout tracking in _trailing_streaks
  - evidence timeout handling in build()
- Added tests in test_ticket_policy.py:
  - evidence_pending marker detection and parsing
  - garbage handling in evidence_pending parsing

## Flow

1. **Build succeeds, evidence times out:**
   - Code is pushed via mr_raiser.push_passing_code()
   - Sidecar written with partial evidence
   - evidence_timed_out outcome returned
   - settle() adds evidence_pending marker to comment
   - Ticket released with retry marker

2. **Evidence retry dispatch (evidence_only):**
   - ticket_pipeline detects evidence_pending marker
   - Dispatches with --evidence-only flag
   - evidence_only() creates/reuses worktree from pushed branch
   - Reads sidecar for prior test results
   - Retries evidence capture
   - Opens PR with accumulated evidence

3. **Cap exceeded:**
   - After MAX_EVIDENCE_RETRIES consecutive timeouts
   - Ticket is parked in needs-info
   - Manual intervention required

## Key Constants

- `EVIDENCE_TIMEOUT_MARKER`: "Evidence capture timed out"
- `MAX_EVIDENCE_RETRIES`: 5 consecutive retries before parking
- `EVIDENCE_PENDING_MARKER`: "marvin:evidence-pending" (hidden HTML comment)

## Testing

Run tests with:
```bash
~/.agents/venv/bin/python -m pytest lib/tests/test_run_ticket.py -v -k evidence
~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_policy.py -v -k evidence
```

## Not Yet Implemented

1. `_agent_builds_per_merged_pr` metric in purpose_metrics.py (tracks efficiency)
2. Full documentation update in docs/life-of-a-ticket.md
3. Characterization test for disk_triggers.decide_merged ignoring PR-less branches
4. Explicit d-breaker handling (verify existing behavior is correct)

## Related Issues

- marvin#95: Pipeline worktree isolation
- marvin#881: Evidence timeout handling
- ADR 0071: Evidence sidecar format
