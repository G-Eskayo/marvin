1. Add `sandbox_orchestration.worktree_path_for(ticket_ref)` (pure helper, reuses `_doc_slug`).
2. Add the pending-evidence marker API to `evidence_capture.py` (`pending_evidence_path`, `read_pending_evidence`, `write_pending_evidence`, `clear_pending_evidence`), with the corrupt/missing/stale/unwritable tolerance from tests 7–8.
3. Write tests 7–8 (marker API) against the real filesystem (tmp_path), no mocks needed.
4. Extract `_raise_with_evidence()` out of `run_ticket.py:build()`'s current post-passing block; wrap its test-results computation in `try/except TestTimedOut`; implement the attempt-counting / give-up-and-raise-anyway logic (point 3 of the design).
5. Write tests 1, 2, 12 against `_raise_with_evidence` and the breaker-walk parametrization.
6. Implement `_resume_pending_evidence()` in `run_ticket.py` and wire it into `build()` before `execute_ticket`; implement the Decision-dependent staleness branch once Decision `stale_base` is answered.
7. Write tests 3, 5, 6, 9, 10, 11 against the resume path.
8. Add the `decide_worktree` early-return in `cleanup_sweep.py`; write test 4.
9. Add the `evidence_timed_out` branch to `run_ticket.py:settle()` (comment marker, stage, breaker, release, redispatch — all reused calls).
10. Add the `_format_test_results` "couldn't capture" branch to `mr_raiser.py`; extend test 2's coverage there.
11. Add `_planning_starts`, `_merged_marvin_prs`, and the new `RATES` entry to `purpose_metrics.py`; write test 14.
12. Confirm/fix test 13 (`_pipeline_verify_timeouts` probe) against the new stage-detail text.
13. Write test 15 (fresh Check-on date) and update the ticket's/PR's Purpose-metric block to use a computed Check-on date instead of the stale one.
14. Measure the baseline: run `_planning_starts`/`_merged_marvin_prs` (or the equivalent manual `gh`/ticket-stages read) against the Mac mini's real `~/.claude/logs/ticket-stages/` and `gh pr list` for 2026-10-23–2026-10-30, and record the resulting number in the PR's Purpose-metric block.
15. Write `docs/adr/0086-evidence-only-retry-keeps-the-worktree.md` recording this design and the answered Decisions.
16. If `cross_machine_resume` is answered A (scratch-ref push): add the scratch-branch push on timeout and the corresponding fetch/resume-on-another-Mac logic, plus a test that `mr_raiser`'s PR-dedupe never confuses a scratch ref with the real PR branch. (Skipped entirely if answered B.)