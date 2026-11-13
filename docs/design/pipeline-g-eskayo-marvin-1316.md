I have everything needed. Here's the plan.

## North-star fit

Reuses the existing stage-reading pattern in `lib/purpose_metrics.py`: `_replanned_tickets` (marvin#606) and `_prd_dispatches` (marvin#448) already glob `ticket_stages.STAGES_DIR`, parse each ticket's JSON array, skip malformed files, and filter by `_when(...)` against a `days`-windowed cutoff — the new probe is a thin variant of that same loop, filtered on `stage == "verifying"`, `status == "failed"`, and `"timed out" in detail.lower()`. The "on this machine" filter reuses `_sync_stuck_episodes`'s machine-match pattern (marvin#702/#706), compared against `machine_profile.registry_id()` — the identity `ticket_stages.record_stage` actually writes into the `machine` field (confirmed by reading `run_ticket.py:389`, which calls `record_stage` for the `timed_out` branch with no `machine=` override, so it defaults to `registry_id()`). Registration itself reuses the `PROBES` dict convention verbatim — no new log, no new job, no new mechanism.

It's the simplest sufficient approach: one more entry in an existing registry, keyed off data the pipeline already writes (the breaker fix, marvin#970, already calls `record_stage("verifying", "failed", ...)` for every timeout). Token cost is small and one-time (one function, ~6 small fixture-only unit tests); it spends nothing per-run beyond an O(stage-events-in-window) file read once a day. It leaves the user more capable: once registered, the daily outcome check on marvin#881's recurrence check can close the loop automatically instead of someone eyeballing logs by hand — exactly the "nothing breaks silently" of north star 2 / ADR 0080 I5.

No decisions needed — the ticket is fully specified and the ambiguous points (which machine identity to compare, how to tell "malformed" from "unreadable" apart) are resolved by reading the existing code's own conventions, not judgment calls for the owner.

## Tests (written first)

In `lib/tests/test_purpose_metrics.py`, fixture-only, `tmp_path`-based (no real `~/.claude/logs`, no network, no `gh`), mirroring `_prd_stages`/`_stages` helpers already there:

1. **Counts correctly and excludes near-misses** — one fixture with: a `verifying`/`failed` event with `"timed out"` in the detail on this machine (counts); a `verifying`/`failed` event with `"TIMED OUT"` in different case (counts — case-insensitive); a `verifying`/`failed` event with `"timeout"` (no space, wrong word — doesn't count); a `done`/`failed` event whose detail says `"timed-out runs"` (non-verify stage — doesn't count, covers the ticket's own break-it bullet); a `verifying`/`passed` event with "timed out" in detail (wrong status — doesn't count).
2. **Machine and window filters** — an otherwise-matching record tagged with a different `machine`, and one with a timestamp outside the window: neither counted (acceptance criterion 3).
3. **The 2026-10-29 baseline fixture** — 20 matching records spread across tickets (mirroring #779/#462 three times each, etc.) inside the stated window → probe returns exactly 20 (recurrence-check baseline reproduced from real shape).
4. **Missing/empty directory → 0** — nonexistent `stages_dir` and an existing-but-empty one.
5. **Malformed file skipped, not fatal** — `corrupt.json` (`"{not json"`), a non-list top-level JSON, and a list containing `None`/non-dict/missing-field entries, alongside one valid matching file — the valid count still comes through.
6. **Unreadable file raises, not 0** — `chmod(0o000)` on one ticket's JSON file (`finally: chmod` back for cleanup): the probe raises rather than returning 0, per the module's "missing is absent, unreadable is unknown" convention (e.g. `_stale_relay`, `code_sync._review_items_raw`).
7. **Registered in PROBES** — `pm.PROBES["pipeline-verify-timeouts"]` exists, limit is `0.0`, and the description names `#881`/`#1316`.

Kept to 7 small, fast, fixture-only tests — no stress/perf test, per the ticket's explicit "keep the test set small and fast: the earlier builds timed out."

## Task List

1. Add `_pipeline_verify_timeouts(stages_dir=None, days=PROBE_WINDOW_DAYS, now=None, machine=None)` to `lib/purpose_metrics.py`, placed next to `_replanned_tickets`/`_prd_dispatches`: glob `stages_dir.glob("*.json")`, catch `ValueError` (malformed JSON) per file and skip, let `OSError` (unreadable file) propagate, filter events on `stage == "verifying"`, `status == "failed"`, `machine == machine_profile.registry_id()` (or override), `"timed out" in str(detail).lower()`, and `_when(timestamp) >= cut`; return `0.0` when `stages_dir` doesn't exist.
2. Register `"pipeline-verify-timeouts": (lambda days=PROBE_WINDOW_DAYS: _pipeline_verify_timeouts(days=days), 0.0, "<description citing #881/#1316>")` in the `PROBES` dict.
3. Write the 7 tests listed above in `lib/tests/test_purpose_metrics.py`.
4. Run `lib/tests/test_purpose_metrics.py` (and the full suite if fast enough) to confirm everything passes and nothing else broke.
5. Update ticket #1316's own `## Recurrence check` wiring is already satisfied by registration — no doc changes needed elsewhere (`incident_ladder.py`, `auto_merge_regression.py`, `CONTEXT.md` all read `PROBES` generically).