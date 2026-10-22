## North-star fit

**Reuses, before adding anything new:**
- `lib/failure_breaker.py` — the per-machine, append-only `~/.claude/logs/pipeline-failures.jsonl` log and its existing `record_failure`/`record_success`/`signature()` primitives (already written by every `run_ticket.py` call). This ticket's AC #1 ("no new state store") is satisfied by adding two small pure functions here (`ticket_streak`, `should_hold`) that read the *same* log the cross-ticket breaker already reads — not a new ledger.
- The **#213 hold/Revisit convention**, which is already fully built end-to-end and currently has zero writers: `lib/ticket_policy.py`'s `parse_revisit_comment`/`latest_revisit`/`is_revisit_due`, `lib/ticket_agents.py`'s `plan_revisit` (the hourly revisit agent), `lib/ticket_pipeline.py`'s `HOLD_LABELS`, `dashboard/electron/main/board.js`'s `hold` board state, and `lib/health_checks.py`'s `check_hold_revisit` (which already complains when a held ticket has *no* Revisit line). This ticket is the **first thing that writes a `Revisit by:` line** — everything downstream already works and needs no change.
- `lib/health_checks.py`'s `check_missing_profiles` (`lib/health_checks.py:612`) as the pattern for the new Health check: injectable `snapshot`/`repos`/`gh`, `ticket_agents.collect()` + `board_repos()`, one result row per repo.
- `lib/project_profile.py`'s `_validate()` per-field validation style (`f"{source}: ..."` `ValueError`s) for the new `failure_threshold` profile field.
- `lib/run_ticket.py`'s existing `_park_stuck_ticket` (needs-info path, used by the unrelated too-vague/verify-timeout callers) — extended with one new optional parameter rather than duplicated.

**Simplest sufficient approach:** the per-ticket counter and the per-project override are two small pure functions plus one new profile field; the label/comment change is one new optional parameter on an existing function, so the two *other* existing callers of `_park_stuck_ticket` (too-vague, verify-timeout-cap) are provably untouched. No new agent, no new file, no cross-machine aggregation for the Health check (the breaker itself already documents that it judges "the dispatches it ran itself" — the per-ticket counter inherits the same accepted per-machine limitation rather than solving a harder problem nobody asked for here).

**Tokens:** spends a small, fixed amount now (a handful of pure functions + tests) to stop the exact failure mode the ticket's own problem statement says was **~70% of pipeline output tokens** (#28: 1,644 failed runs, #30: 1,247, #94: 456). Highest-leverage token save available in the pipeline today.

**Phone-OS fit:** tangential, but it is a reliability precondition ("nothing may break silently") for MARVIN running unattended for long stretches.

**User capability:** Gil stops discovering retry storms after the fact in usage accounting; a stuck ticket now surfaces itself (held, with its failure signatures, a Revisit date, and a Health row) instead of silently burning budget. It does not remove judgment from him — a held ticket still needs a person or the revisit date to move again.

The ticket's "Solution" doesn't state its own north-star fit, so nothing to correct there.

---

## Tests to write first

The ticket has no "How we'll try to break it" section (missing since before ADR 0063's gate existed; the ticket pre-dates that requirement and was never re-triaged). Deriving misuse cases from the standard categories instead:

**`failure_breaker.ticket_streak` / `should_hold` (new):**
1. N mixed-signature failures in a row reaches the threshold → held.
2. 2 *identical* signatures in a row holds immediately, even below threshold.
3. A success in between resets the count (AC's explicit scenario).
4. A single failure, below threshold, no repeat → not held.
5. Empty/missing log file → `{"count": 0, "signatures": []}`, never held.
6. A corrupt (non-JSON) log line never crashes it (mirrors `test_a_corrupt_log_line_never_crashes_the_breaker`).
7. Records for a different ticket or a different project interleaved in the shared log are never counted (project+ticket scoping).
8. A manual `clear()` record (the systemic breaker's own reset) does **not** reset a per-ticket streak — a person clearing the environment-wide breaker must not silently un-stick a genuinely stuck ticket.
9. `threshold=0`, negative, or `None` passed directly → defensive fallback to 3, never disables the guard (a person's/profile's mistake).
10. A few thousand failure records for one ticket (the actual #28 shape) still returns promptly and correctly — bounded-time guard.

**`project_profile._validate` (`failure_threshold`):**
11. Field omitted → defaults to `None`.
12. A positive int → accepted verbatim.
13. A bad value (string, float, `0`, negative, `True`) → `ValueError` naming the field, matching existing style.

**`ticket_policy` (hold label + new `format_revisit`):**
14. `"hold"` added to `STATE_LABELS` so `triage_verdict`/`plan_triage` **skip** an already-held ticket instead of re-labelling it `ready-for-agent` on the next hourly triage pass — a real correctness bug today's code would hit the moment this ships (verified by reading `plan_triage`/`triage_verdict`: nothing currently filters out `hold`).
15. `format_revisit(date, condition)` round-trips through the existing `parse_revisit_comment` (with and without a condition).

**`run_ticket.py` integration:**
16. A failure reaching a project's own `failure_threshold` override is held using that number, not the hard-coded default.
17. marvin (no profile) keeps the default threshold of 3, unchanged.
18. The hold comment carries the failure signatures (truncated) and a **bare** `Revisit by: ... — ...` line on its own line, parseable by the existing regex (guards the exact "line not bare" defect the previous failed attempt's own plan called out).
19. `_park_stuck_ticket(..., hold_data=None)` is byte-identical to today (needs-info, no signatures, no Revisit line) — regression guard for the two existing unrelated callers (too-vague, verify-timeout cap), which must not change.
20. Claim + `ready-for-agent` removal on the hold path still happens exactly as before.
21. A failing `gh` call during the hold edit/comment never stops the rest of the park (mirrors `test_a_failing_gh_call_never_stops_the_rest_of_the_park`).
22. Rewrite the two existing tests that assert the *old* comment-based counting (`test_consecutive_failure_streak_counts_trailing_failure_comments`, `test_consecutive_failure_streak_resets_on_a_human_comment`) against the new jsonl-based behavior — this is a deliberate, AC-required behavior change (a human comment no longer resets the count; only a recorded success does).
23. A non-marvin project's failure feeds `failure_breaker` with its own `project=repo`, and the streak/hold check is scoped to that project (mirrors the existing cross-project isolation tests).

**`health_checks.check_retry_storm_holds` (new):**
24. No repos / no held tickets → `[]`.
25. A ticket labeled `hold` whose jsonl streak is 0 (held for an unrelated reason, e.g. a person pinned it) is **not** reported — must not misattribute every hold to this rule.
26. Multiple held tickets across repos are all reported, sorted, each with a readable detail; truncated at a sane cap.
27. One repo's `gh`/`collect` failure doesn't take down the whole check (reuses `collect()`'s existing per-repo try/except).

**CONTEXT.md**: a doc edit, not unit-testable; satisfied by the edit itself.

---

## Decisions

<!-- marvin:decisions -->
### revisit_days: How many days before a held ticket is automatically revisited?
- [ ] A: 7 days
- [ ] B: 14 days
- [ ] C: 30 days

(No existing convention to derive this from — `format_revisit`'s first-ever caller has to pick a number. I'll treat the Health check's severity as my own implementation call, not an owner decision: yellow when any ticket is currently held by this rule, green otherwise — mirroring `check_hold_revisit`'s existing tone, since a held ticket is the system working as designed, not an active break.)

## Task List

1. **`lib/failure_breaker.py`** — add `ticket_streak(ticket, project=MARVIN) -> dict` (`{"count", "signatures"}`, oldest-first, scoped to this ticket+project since its last recorded success, ignoring `clear` records) and `should_hold(ticket, project=MARVIN, threshold=3) -> dict | None` (`{"count", "signatures", "condition"}` or `None`; trips on `threshold` reached *or* the last two non-empty signatures matching; defensively clamps a bad `threshold` to 3). Tests 1–10 first.
2. **`lib/project_profile.py`** — in `_validate()`, add `profile.setdefault("failure_threshold", None)` and validate: `None` or a positive `int`, else `raise ValueError(f"{source}: failure_threshold must be a positive int")`. Tests 11–13 first.
3. **`lib/ticket_policy.py`** — add `"hold"` to `STATE_LABELS`; add `format_revisit(date: str, condition: str | None = None) -> str` next to `parse_revisit_comment`. Tests 14–15 first.
4. **`lib/run_ticket.py`**:
   - `_consecutive_failure_streak(issue_number, repo=REPO)` — keep its exact signature (existing seam), change its body to `return failure_breaker.ticket_streak(issue_number, project=repo)["count"]`.
   - Add `DEFAULT_REVISIT_DAYS` constant (value from the Decision above).
   - At the generic-failure call site (`run_ticket.py:364-375`): compute `threshold = (profile or {}).get("failure_threshold") or MAX_CONSECUTIVE_FAILURES`; after `failure_breaker.record_failure(...)` runs, call `hold_data = failure_breaker.should_hold(issue_number, project=repo, threshold=threshold)`; park only when `hold_data is not None`, passing it through; keep the retry-backoff comment path for the non-held case using `_consecutive_failure_streak` as today.
   - `_park_stuck_ticket` — add `hold_data: dict | None = None`. When set: label `"hold"` (not `needs-info`), comment lists the failure signatures (truncated) and ends with a bare line from `ticket_policy.format_revisit(today + DEFAULT_REVISIT_DAYS, hold_data["condition"])`. When `None` (the two existing callers): unchanged.
   - Tests 16–21 first, then rewrite tests 22 (the two comment-based streak tests).
5. **`lib/health_checks.py`** — add `check_retry_storm_holds(snapshot=None, repos=None, gh=None) -> list[dict]` mirroring `check_missing_profiles`'s injectable-snapshot pattern: per repo, find `hold`-labeled issues, keep those with `failure_breaker.ticket_streak(number, project=repo)["count"] > 0`, report each (severity yellow, truncated). Register it in `default_checks()`. Test 27 reuses `collect()`'s own per-repo isolation; tests 24–26 first.
6. **`CONTEXT.md`** — extend the existing "Profile fields" bullet (`### Per-project execution profiles`) to mention `failure_threshold`; add a short new subsection right after that section documenting: the retry-storm problem (#28/#30/#94), the mechanism (reads `pipeline-failures.jsonl` via `failure_breaker.ticket_streak`/`should_hold`, no new state store), that it reuses the `hold`/`Revisit by:` convention from #213 so the revisit agent and dashboard pick it up unchanged, the new Health check, and the per-machine (not cross-machine) counting caveat inherited from the breaker.
7. Run `pytest lib/tests/` and `npx vitest run` (dashboard; no JS touched, sanity pass only) before considering it done.