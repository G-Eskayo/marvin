1. **`lib/failure_breaker.py`**:
   - Add `record_hold(ticket: int, project: str = MARVIN, now: datetime | None = None) -> None`, appending `{"kind": "hold", "ticket", "project", "t"}` — mirrors `record_success`/`clear` exactly.
   - `ticket_streak`: change `r["kind"]`/`f["sig"]` to `r.get("kind")`/`f.get("sig")`; treat `kind == "hold"` for this ticket+project as a reset point alongside `success`; filter out `sig == MODEL_UNAVAILABLE_SIG` from both `count` and `signatures`; drop the unused `now` parameter (never used in the body).
   - Add module constant `MODEL_UNAVAILABLE_SIG = "model-unavailable"`; use it in `signature()`'s existing return and in the new filter.
   - `should_hold`: accept an optional precomputed `streak: dict | None = None` (default: call `ticket_streak` itself, backward compatible); compare only non-empty signatures for the repeat check; drop unused `now`.
   - Write tests 1–18 first.
2. **`lib/ticket_policy.py`**: no further code change (STATE_LABELS/`format_revisit` already correct from the prior attempt) — just add test 30 to `test_ticket_policy.py` (not a new file).
3. **`lib/project_profile.py`**: fix the bool-passes-as-int gap in `_validate()`'s `failure_threshold` check (`isinstance(ft, bool)` excluded explicitly). Write tests 33–34 first (32 already exists).
4. **`lib/run_ticket.py`**:
   - `_park_stuck_ticket`: in the `if hold_data:` branch, call `failure_breaker.record_hold(issue_number, project=repo)` right after appending the revisit line.
   - `run()`'s failure branch: compute `streak_data = failure_breaker.ticket_streak(issue_number, project=repo)` once; pass it into `failure_breaker.should_hold(issue_number, project=repo, threshold=threshold, streak=streak_data)`; use `streak_data["count"]` for both the retry-line attempt number and the `_park_stuck_ticket` streak argument — removing the two redundant re-reads.
   - Write tests 19–29 first.
5. **`lib/health_checks.py`**: no code change (prior attempt's `check_retry_storm_holds` has no must-fix findings) — tests 26–30 (from the prior design) carried over unchanged.
6. **`CONTEXT.md`**: correct the reset-mechanism description (success / clear / a hold itself, not "times out indefinitely"); add the model-unavailable-exclusion note; name the per-machine caveat specifically for the new health check, not just generically.
7. Run `pytest lib/tests/` (full suite — confirm the net regression count is zero beyond the deliberate rewrite of `test_repeated_usage_limit_releases_wait_longer_each_time`) and `npx vitest run` in `dashboard/` as a no-op sanity check (no JS touched).