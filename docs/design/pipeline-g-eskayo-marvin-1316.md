# Pipeline Verify Timeouts Recurrence Probe

## Overview

This ticket adds a new recurrence probe to catch pipeline verify timeouts that occur during the ticket-stage lifecycle, independent of whether the log-feeding step to `pipeline-failures.jsonl` succeeded. The probe reads from the unconditional `ticket-stages` JSON records written by `run_ticket.py:389`, making it a complementary check to the existing `verify-timeouts` probe (#1152).

## Approach

Reuses the ticket-stage-reading pattern already established in `lib/purpose_metrics.py`:
- `_replanned_tickets` (marvin#606, line 173) and `_prd_dispatches` (marvin#448, line 197) already glob `ticket_stages.STAGES_DIR`, parse each ticket's JSON array, skip malformed files, and filter by time window.
- The new probe is a thin variant: filter on `stage == "verifying"`, `status == "failed"`, and `"timed out" in detail.lower()`.
- Machine identity reuses `machine_profile.registry_id()`, the same value `record_stage` itself defaults to.
- The unreadable-vs-missing split (`OSError` propagates; missing directory is `0.0`) follows the pattern in `code_sync._review_items_raw` and `_stale_relay`.

## Rationale

#881's bug was that `run_ticket.py:390` (the log-feeding call to `_feed_breaker`) used to get skipped for timeouts. This probe reads the ticket-stage record written one line earlier (line 389), unconditionally, by `record_stage` itself. The two counts are expected to move together now that #881/#970 is fixed — that's what makes this an independent recurrence check: if the breaker call ever silently dropped again, #1152's probe would read low/zero while this one would still catch it.

The ticket carries a recurrence check with baseline 20 events from 2026-10-29, as documented in the Acceptance Criteria. Any new timeouts during the probe window signal the symptom has returned.

## Implementation

### Function: `_pipeline_verify_timeouts()`

Added to `lib/purpose_metrics.py` after line 218:
- Resolves `stages_dir` to `ticket_stages.STAGES_DIR`
- Returns `0.0` immediately if directory doesn't exist
- Resolves time window cutoff and machine identity
- Globs `*.json` files in the stages directory
- Catches only `ValueError` per file (lets `OSError` propagate for unreadable files)
- Skips non-list JSON and malformed entries
- Counts events matching all criteria: `stage == "verifying"`, `status == "failed"`, matching machine, `"timed out"` in detail (case-insensitive), within time window

### Registration

Added to `PROBES` dict with threshold 0.0, threshold comment, and cross-references to both #881 and #1316.

### Tests

Seven fixture-only tests appended to `lib/tests/test_purpose_metrics.py`:

1. **Counts correctly and excludes near-misses** — verifies case-insensitive matching, rejects wrong stage/status, skips entries without "timed out"
2. **Machine and window filters** — different machine and outside time window are excluded
3. **Baseline reproduces 2026-10-29 episode** — 20 matching events returns exactly `20.0`
4. **Missing and empty directory return 0** — nonexistent and empty-but-real directories both return `0.0`
5. **Malformed files skipped, not fatal** — corrupt JSON, non-list top-level, incomplete dicts don't break; valid entries still counted
6. **Unreadable file raises OSError** — permission-denied file propagates error, doesn't return `0.0`
7. **Registration verified** — probe exists in `PROBES` with limit `0.0` and correct ticket references

## Files Changed

- `lib/purpose_metrics.py` — add `_pipeline_verify_timeouts()` function and PROBES entry
- `lib/tests/test_purpose_metrics.py` — add 7 tests with `_verify_stage` helper
- `docs/design/pipeline-g-eskayo-marvin-1316.md` — this document
- `docs/design/pipeline-g-eskayo-marvin-1316-tasks.md` — task list

No changes needed to `incident_ladder.py`, `auto_merge_regression.py`, or `CONTEXT.md` — all read `PROBES` generically.

## Acceptance Criteria

- Probe reads ticket-stage JSON unconditionally, independent of log-feeding step
- Time window: 7-day default window via `PROBE_WINDOW_DAYS`
- Machine identity: filters to specific machine, summed across Macs by `measure_everywhere`
- Case-insensitive "timed out" string match in detail field
- Threshold: 0.0 — any single timeout occurrence is worth flagging for #881's recurrence check
- All 7 tests pass; no regressions in existing tests
