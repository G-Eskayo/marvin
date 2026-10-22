## North-star fit

**Reuses, before adding anything new** (unchanged from the prior attempt's correct calls, now actually followed through on):
- `lib/failure_breaker.py`'s `pipeline-failures.jsonl` log and its `record_failure`/`record_success`/`clear`/`_read()` — still the only state store touched (AC #1). The fixes below extend this module's existing functions (`ticket_streak`, `should_hold`) and add one more append-only `kind`, not a new log or file.
- `lib/ticket_policy.py`'s `hold`/`Revisit by:` convention (#213) and the already-built `revisit` ticket agent — unchanged, still reused as-is.
- `lib/run_ticket.py`'s `_consecutive_failure_streak`/`_park_stuck_ticket` seam functions — kept in place, signatures unchanged (still monkeypatched by ~20 existing tests).
- `lib/health_checks.py:check_missing_profiles`'s injectable `snapshot`/`gh`/`repos` pattern — unchanged.
- The global `_isolate_failure_breaker_log` autouse fixture already in `lib/tests/conftest.py:107` (confirmed by reading it) — every new test below writes to this isolated temp log for free; no test needs its own `LOG_PATH` monkeypatch.

**Why this attempt is different, not just "simplest sufficient" again:** the previous attempt's code review found 4 must-fix defects, and reading the current (uncommitted) diff turned up a 5th the review's own wording pointed at but didn't name outright. All five share one root cause: **`ticket_streak`/`should_hold` were written as if every record in the log means the same thing, when three kinds of records need different treatment** — a model-unavailable failure isn't a strike, a malformed/old record must degrade gracefully, and a *hold* itself must be a reset point (not just success/clear). Fixing the read logic once, correctly, fixes all five:

1. **(review #1)** `should_hold` must compare the last two *non-empty* signatures, not raw ones — guards against a future record with a missing `sig` key producing two `None`s that look like a match.
2. **(review #2)** `ticket_streak` uses `r["kind"]`/`f["sig"]` without `.get()` — a parseable-but-incomplete jsonl line KeyErrors inside `run()`'s failure branch, so the failure is silently never commented or parked.
3. **(review #3 — the real logic gap, not just a doc caveat)** nothing resets the per-ticket streak when a held ticket is released. **Fix:** add `failure_breaker.record_hold(ticket, project)`, written by `_park_stuck_ticket` itself the moment it holds a ticket, and treat `kind == "hold"` as a reset point in `ticket_streak` exactly like `success`. This means every hold starts the *next* attempt with a clean streak — the park comment's instructions ("remove `hold`, add `ready-for-agent`") become true again, without needing to detect the release event at all (which GitHub doesn't expose a clean hook for). No new state store: still the same log, one more `kind` value.
4. **(review #4)** the tautological test monkeypatched `ticket_streak` to always return 0, which hid a real bug: **`ticket_streak` currently counts model-unavailable failures toward the per-ticket threshold**, contradicting the existing code comment "Model failures are recorded in failure_breaker but don't count toward per-ticket threshold" (`run()`'s own in-code claim, now false). Fix: filter `sig == "model-unavailable"` out of both the count and the signature list in `ticket_streak`, then rewrite the test against the *real*, unmonkeypatched function.
5. **(found while reading, not in the ticket text)** `lib/tests/test_ticket_policy.py:118`'s `test_already_triaged_tickets_are_left_alone` enumerates `STATE_LABELS` by hand and was never updated for `"hold"` — the previous attempt's self-described "required fix" (STATE_LABELS) shipped with **no regression test in the file that already tests exactly this**, in a file the previous diff never touched. That's precisely the kind of self-defeating gap code review exists to catch.

**Also fixing, not in the review's must-fix list but required by [[feedback-space-time-complexity-equal]] (O(N) re-reads are a correctness defect, #447):** the current diff re-reads and re-scans the whole jsonl log three separate times per single failure (`should_hold`'s internal `ticket_streak` call, then a second explicit `ticket_streak` call to get `streak` for `_park_stuck_ticket`, then a third via `_consecutive_failure_streak` inside `_comment_failure`'s retry-line branch). `should_hold` already computes and returns `count`; threading that single computed value through removes two of the three reads with no new code, only less of it.

**Not changing (verified, not re-decided):** `lib/run_ticket.py`'s `datetime`/`timedelta`/`timezone` imports (review flagged as "worth verifying") — confirmed present at line 33; the module already imported them for `_retry_line`. No fix needed. The per-machine counting caveat (`pipeline-failures.jsonl` is per-machine) stands as AC #1 requires it — still documented in CONTEXT.md, now with the health-check-specific instance of it named explicitly (review's health_checks.py:636 note), not just the general case.

**Tokens:** saves — this is the mechanism that stops the retry storms responsible for ~70% of output tokens in usage accounting ([[project-usage-accounting-run-natively]]). The redundant-read fix above also cuts real per-run I/O, not just tokens. Spends — negligible: one more `kind: "hold"` line in an already-written-to log.

**Phone-OS direction:** neutral (internal pipeline hygiene, north star 1).

**More capable or more passive:** more capable — a released, held ticket now actually gets the fresh shot its park comment promises, instead of silently re-holding within one run; Gil stops being told "remove `hold` and retry" by a system that was lying about what retrying would do.

## Tests (write first)

No "How we'll try to break it" section exists on the ticket (confirmed by re-reading it); this is an internal, no-outside-input mechanism, so the adversarial/injection clause doesn't apply. List below is the misuse-category sweep plus the AC's explicit cases, **with every one of the 5 defects above paired to the specific test that would have caught it**, marked `[REGRESSION]`.

**`lib/failure_breaker.py` (`test_failure_breaker.py`)**
1. N consecutive mixed-signature failures → `ticket_streak()["count"] == N`.
2. A success in between two failure groups → count only reflects failures after the success.
3. A manual `clear` also resets the per-ticket count.
4. Two identical signatures as the last two entries → `should_hold()` returns `{"reason": "repeat-signature", ...}` even below threshold.
5. Signatures A, B, A (not consecutive) → repeat-signature does not fire.
6. Below threshold, no repeat → `should_hold()` is `None`.
7. `threshold` 0/negative/`None` → count-rule disabled, repeat-signature rule still fires.
8. Old log lines with no `project` key default to `G-Eskayo/marvin`.
9. **[REGRESSION — review #2]** A parseable jsonl line missing `kind` or `sig` sits among real records for this ticket → `ticket_streak`/`should_hold` never raise `KeyError`, and the malformed record still counts toward `count` but is excluded from the signature-repeat comparison.
10. **[REGRESSION — review #1]** Two failures whose `sig` is missing (`None`, via the same malformed-record path as test 9) are never treated as a "repeat" — `should_hold` only compares non-empty signatures. Without this, two unrelated unclassified failures would hold a ticket after 2 runs.
11. Same ticket number in two different projects never cross-contaminates counts.
12. Empty/missing log file → count `0`, `should_hold()` is `None`.
13. ~2,000 records (realistic #28/#30 scale) completes correctly and in bounded time (<1s).
14. Two interleaved append sequences for the same ticket+project, written out of wall-clock order → streak still keys off file/append order, not timestamp order.
15. **[REGRESSION — review #3]** `record_hold(ticket, project)` resets `ticket_streak` for that ticket+project going forward: 3 failures, then `record_hold`, then 1 new failure (even same signature as before) → `ticket_streak()["count"] == 1`, `should_hold()` is `None` (not re-held on the very next attempt). This is the test the previous attempt was missing entirely — there was no mechanism to catch, because there was no reset mechanism.
16. **[REGRESSION — review #4, hidden bug]** Two model-unavailable failures interleaved with one real failure → `ticket_streak()["count"] == 1` and `signatures == [<the real sig>]` (model-unavailable entries excluded from both).
17. A real failure, a model-unavailable failure, then the same real signature again → `should_hold()` still fires `repeat-signature` (the model-unavailable entry doesn't break adjacency in the filtered signature sequence).
18. `record_hold` is a `kind: "hold"` append, like `record_success`/`clear` — a `tripped()` call across the same window is unaffected by `hold` records (cross-ticket breaker must only ever look at `failure`/`success`/`clear`).

**`lib/run_ticket.py` (`test_run_ticket.py`)**
19. `_consecutive_failure_streak` delegates to `failure_breaker.ticket_streak(...)["count"]` (already covered by the existing rewritten tests at lines 334–349; kept as-is).
20. **[REGRESSION — review #4]** Rewrite `test_repeated_usage_limit_releases_wait_longer_each_time` to **stop monkeypatching `failure_breaker.ticket_streak`**, let 3 real `ModelRunFailed` runs write real `record_failure` entries, and assert `rt._consecutive_failure_streak(454) == 0` against the real, unmonkeypatched function — this is the test that must fail against today's code (before the fix 16/17 lands) and pass after.
21. A profile's `failure_threshold` override holds at N≠3.
22. No profile / `failure_threshold` absent → falls back to `MAX_CONSECUTIVE_FAILURES`.
23. `_park_stuck_ticket(..., hold_data=None)` is byte-identical to current timeout/too-vague behavior (pinning test).
24. `_park_stuck_ticket(..., hold_data={...})` → labels `hold`, comment carries truncated signatures and a bare `Revisit by:` line, **and calls `failure_breaker.record_hold(issue_number, project=repo)` exactly once**.
25. End-to-end `run()`: two consecutive failures with an identical signature hold immediately, far below threshold.
26. End-to-end `run()`: failure, success, N-1 more failures never holds.
27. **[REGRESSION — review #3, end-to-end]** `run()` parks ticket X (hold); a second `run()` call for X with one more failure of the *same* signature as the one that triggered the hold does **not** park again — it releases normally via `_release_claim`. This is the end-to-end version of test 15 and is the direct proof the "misleading park instructions" bug is gone.
28. Documented per-machine limitation: a failure recorded against one machine's log is invisible to `ticket_streak()` pointed at a different machine's log (explicit, intentional).
29. Redundant-read fix: `should_hold`'s returned `count` is reused by the hold branch instead of a second `ticket_streak()` call — assert via a call-counting spy on `failure_breaker.ticket_streak` that `run()`'s single-failure path calls it **at most once** (regression guard against the 3-reads-per-failure regression above).

**`lib/ticket_policy.py` (`test_ticket_policy.py`, `test_ticket_policy_revisit.py`)**
30. **[REGRESSION — gap found in review, missing test]** Add `"hold"` to the enumerated labels in `test_already_triaged_tickets_are_left_alone` (`test_ticket_policy.py:118`) — `triage_verdict()` must return `None` for a `hold`-labeled ticket. This is the exact self-defeating-bug guard the previous attempt claimed to add but never tested.
31. `format_revisit(date)` / `format_revisit(date, condition)` round-trip through `parse_revisit_comment` (already covered at lines 220–230; kept as-is).

**`lib/project_profile.py` (`test_project_profile.py`)**
32. `failure_threshold`: absent → `None`; positive int passes; `0`, negative int, non-numeric string raise (already covered, kept).
33. **[REGRESSION — review's `isinstance(True, int)` note]** `failure_threshold: true` (a bool) raises `ValueError` — `isinstance(True, int)` is `True` in Python, so the bare `isinstance(ft, int)` check silently accepts booleans as valid thresholds (1/0) without this test and fix.
34. `failure_threshold: 1.5` (a float) raises.

**`lib/health_checks.py` (`test_health_checks.py`)** — unchanged from the prior attempt's tests 26–30 (green/0 case, title+number naming, excludes unrelated holds, per-repo failure isolation, injectable snapshot); no defects found here, kept as-is.

**`CONTEXT.md`** — documentation only, verified by review: corrected to describe the real reset mechanism (success, clear, **or a hold itself**, per fix 3) instead of the inaccurate "times out indefinitely" phrasing the review flagged, plus the model-unavailable exclusion and the health-check-specific instance of the per-machine caveat.

## Decisions

<!-- marvin:decisions -->
### revisit_window: How many days until a failure-held ticket's `Revisit by:` date, so the revisit agent (#213) brings it back automatically?
- [ ] A: 7 days
- [ ] B: 14 days
- [ ] C: 30 days
- [ ] D: No automatic date — hold indefinitely until a person acts (relies on Health's existing "no revisit line" warning instead)

## Task List

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