## Summary

Enriches held-ticket status messaging with contextual hold information and improves hold label validation. When a ticket is held by a person, the rework status now shows who held it, when, and any associated comment. The health check now detects contradictory label combinations: multiple hold labels, or hold + pipeline labels (which is semantically invalid since hold blocks the pipeline).

### Changes

#### Backend (Python)

- **lib/rework_status.py**:
  - Add constants `HOLD_COMMENT_WINDOW_S = 300` (5-minute window for comment association) and `HOLD_COMMENT_MAX_CHARS = 300` (truncation threshold)
  - Add `_gh(args, timeout=10)` module-level helper (mirrors `ticket_agents._gh()`) for consistent GitHub API calls
  - Add pure `_latest_hold_event(stdout)` function to parse event-call output and select the most recent labeled event (skips malformed lines)
  - Add `_comment_near(gh, repo, number, when)` helper to find a comment within the window; returns None on any error (never raises)
  - Rewrite `_hold_info()` to use the new helpers for cleaner, more maintainable logic
  - In `status_for()` held branch: include comment from hold info, truncated at `HOLD_COMMENT_MAX_CHARS`, alongside who/when
  - Fall back to generic message only when hold dict itself is absent
- **lib/health_checks.py**:
  - Rewrite `check_contradictory_hold_labels()` to detect two types of contradictions:
    1. Multiple hold labels (e.g., both `hold` and `held`)
    2. Hold label + pipeline label (`ready-for-agent` or `needs-reengagement`) — semantically invalid since hold blocks dispatch
  - Mirror `check_missing_profiles()`'s injection shape: use `ticket_agents.collect(repos, gh=gh or ticket_agents._gh)` when snapshot is None
  - Cap output at 5 individual finding cards + one "+N more" summary card (cap at 5 avoids flooding the Health tab)

### Tests

Added comprehensive regression tests:
- **test_rework_status.py**: 
  - `_latest_hold_event()` parsing (latest timestamp, malformed line skipping, empty input)
  - `_comment_near()` (comment within window, outside window, error handling)
  - `_hold_info()` dict return with comment
  - `status_for()` comment truncation at `HOLD_COMMENT_MAX_CHARS`
- **test_health_checks.py**:
  - Contradictory hold labels detection (multiple hold labels, hold + pipeline labels)
  - Capping at 5 + summary card

All 260 related tests (rework_status, health_checks, ticket_agents, ticket_policy) pass. No regressions.

### Design Decision: Refuse, not auto-remove (unchanged from prior attempt)

This implementation **does not automatically remove hold labels**, instead requiring explicit removal:
- **Why refuse**: A person held a ticket for a reason. Automatic removal after a time window could rebuild code they intentionally paused, potentially overwriting their feedback or re-running work they said to wait on. The hold is their explicit choice; removing it should be equally explicit.
- **Consequence**: Held tickets stay held until the person removes the label. The dashboard surfaces who held it and when, so staleness is visible if needed.

This matches the existing design for "claimed" labels: the pipeline respects the label and waits for explicit removal, never an automatic timeout.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
