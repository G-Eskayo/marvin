## North-star fit

**Reuses before adding anything new:** `lib/failure_breaker.py`'s existing `~/.claude/logs/pipeline-failures.jsonl` (already logs every ticket failure/success with a computed `sig`, keyed by `ticket` + `project` — this *is* the "pipeline-failures.jsonl" AC1 names, nothing new to build); `lib/run_ticket.py`'s existing `MAX_CONSECUTIVE_FAILURES = 3` 3-strike guard and `_park_stuck_ticket`/`_consecutive_failure_streak` (the ticket already half-exists — today it counts GitHub-comment strikes and parks to `needs-info`, not `hold`); `lib/ticket_policy.py`'s `parse_revisit_comment`/`latest_revisit`/`is_revisit_due` (the exact `Revisit by:` convention from #213, already shipped, already mirrored in JS); `lib/project_profile.py`'s `_validate()` defaulting pattern for the per-project override; `lib/health_checks.py`'s `check_hold_revisit`/`check_project_tags` four-way (missing/stale/empty/N-named) shape for the new Health check. Net-new code is small: a per-ticket streak/signature reader in `failure_breaker.py`, a label/comment swap in two existing functions, one new Health check, one new profile field.

**Simplest sufficient approach:** no new state store, no new ticket agent, no new state file for Health — the same jsonl log already written on every run answers the counter, the streak, and the "is it currently held" question for both the live pipeline decision and Health's display, so there's exactly one source of truth instead of two (today there are *two* divergent per-ticket counters: `run_ticket.py`'s GH-comment scan and `health_checks.py`'s own separate GH-comment scan — this folds them into one).

**Token/cost:** net *saves* tokens and GitHub-API budget, it doesn't spend more. `check_ticket_failure_streaks` today makes one `gh issue view --json comments` call *per claimed ticket* every 15 minutes just to recount a streak the jsonl log already has for free; switching it to a local file read removes that per-ticket network cost (CONTEXT.md's "GitHub request budget" section flags this budget as a real, previously-exhausted resource). The retry-storm problem itself was ~70% of output tokens (#28/#30/#94); this literally caps that cost going forward.

**Phone-OS / capability fit:** this is reliability plumbing ("nothing may break silently" — north star 2), not user-facing capability, so it doesn't move the needle on north star 2 directly, but it does leave the user (Gil) more capable: a stuck ticket now surfaces itself with a cause and a date to look again, instead of silently burning paid model time for days while still looking "blocked" on the board — less firefighting, not less agency.

**Correction to the ticket's own stated shape:** the ticket's "Solution" section doesn't literally match the repo's own triage convention's exact wording, but `lib/ticket_policy.py:191` explicitly whitelists "Solution" as satisfying "What to build" (and names `#218` by number in its own comment as one of the tickets this exemption exists *for*). So the owner's triage-bot comment ("missing a 'What to build' section") is stale — already fixed by the repo's own triage logic, which the comment predates having been re-run against. **However**, the ticket genuinely has no `## How we'll try to break it` section at all (confirmed by reading the live issue body) — `has_break_it()` would currently flag this ticket as `needs-info` for that reason alone (ADR 0063 gate 1, `lib/ticket_policy.py:194-196`), independent of the owner's comment. The `ready-for-agent` label on it today is therefore stale too. I'm treating the acceptance criteria's own "Tests:" bullet as the de-facto break-it section (it's concrete enough to build from) and filling the gaps myself below, per this ticket's "make the most reasonable call" instruction, rather than bouncing it back to `needs-info`.

## What's already built vs. what #218 actually changes

Reading `lib/run_ticket.py` and `lib/failure_breaker.py` shows most of the machinery already exists, built for a narrower purpose:

| Exists today | Gap #218 closes |
|---|---|
| `MAX_CONSECUTIVE_FAILURES = 3` (`run_ticket.py:36`) | Already the right default — no change, just make it overridable per-project |
| `_consecutive_failure_streak()` counts trailing `FAILURE_MARKER` **GitHub comments** | AC1: must read `pipeline-failures.jsonl` instead (no new store — reuse `failure_breaker`'s existing log) |
| Streak resets on **any** non-failure comment (a human replying at all) | AC4/"Tests": must reset **only** on a recorded success — a bystander comment shouldn't quietly un-stick a broken ticket |
| `_park_stuck_ticket()` adds `needs-info`, removes `ready-for-agent` + claim | Ticket explicitly says `hold`, not `needs-info` — switch the label, keep the ordering protection |
| Park comment has `PARKED_MARKER` + reason + findings | Add the failure **signatures** (already computed by `failure_breaker.signature()`) + a `Revisit by:` line (#213's convention) |
| Nothing checks "same signature twice in a row" | New: 2 identical trailing signatures parks immediately even below N |
| `check_ticket_failure_streaks()` (Health) re-scans GH comments per claimed ticket, marvin only | AC3: switch to the same jsonl source (cheaper, consistent), add a distinct "held by this rule" view, extend to profiled projects |
| `project_profile.py` has no failure-count field | AC1 "per-project override": add `failure_threshold` (or similarly named) to the profile schema |
| Nothing documents this in CONTEXT.md | AC5 |

A real risk I found and will fix as part of this, not as scope creep: `_park_stuck_ticket` removes `ready-for-agent` and would add `hold` with **no other state label** left on the ticket. `lib/ticket_policy.py:14` `STATE_LABELS` (which gates `triage_verdict`'s re-triage skip) does **not** include `"hold"` — so on the next hourly `triage` pass, a held ticket with a well-formed body would get `ready-for-agent` re-added by the triage agent, silently undoing the hold and reopening the exact retry storm this ticket exists to stop. (The existing code avoids this today only because it adds `needs-info`, which *is* in `STATE_LABELS`.) Fix: add `"hold"` to `STATE_LABELS`. This is minimal, correct on its own terms (`hold` is already a real terminal ticket state per #213 — the Backlog "On hold" group, the dispatcher's `HOLD_LABELS` filter, the `revisit` agent's lifecycle), and necessary for AC2 to actually hold.

## Design

**`lib/failure_breaker.py`** — add one pure function, reusing `_read()`/the reset-on-success logic already in `tripped()`:
```python
def ticket_streak(ticket: int, project: str = MARVIN, now: datetime | None = None) -> dict:
    """Trailing failures for ONE ticket in ONE project since its last recorded success (or ever).
    {"count": int, "signatures": [sig, ...]} (oldest-to-newest). Empty/no entries -> count 0."""
```
Mirrors `tripped()`'s "a success resets, a stale/corrupt line never takes it down" handling, but keyed to one ticket, not a cross-ticket signature group. No window (`WINDOW_HOURS` doesn't apply here — a streak doesn't expire with time, only a success clears it, matching the AC's "a success in between resets the count").

Add the park decision as its own pure function (so run_ticket.py and health_checks.py share one answer):
```python
def should_hold(ticket: int, project: str, threshold: int, now=None) -> dict | None:
    """None if not yet due to hold. Else {"reason": "n-failures"|"repeat-signature", "count", "signatures"}."""
```
`reason="repeat-signature"` when the last two signatures match (even if `count < threshold`); `reason="n-failures"` when `count >= threshold`.

**`lib/project_profile.py`** — one line in `_validate()`: `profile.setdefault("failure_threshold", None)` (None = "use the pipeline default", so marvin's constant stays the single source for its own default, and a profile only overrides when a project genuinely needs a different N). Document in the "Profile fields" bullet list (CONTEXT.md:707-711).

**`lib/run_ticket.py`**:
- `_consecutive_failure_streak` → delete the GH-comment implementation; replace its one call site (line 286) with `failure_breaker.ticket_streak(issue_number, project=repo, ...)`-derived count (keep the function *name* if existing tests monkeypatch it as a seam — check at implementation time whether to keep a thin wrapper or rename call sites directly; several tests already monkeypatch `rt._consecutive_failure_streak` as their seam, so keeping the name with a new body is the lower-churn path).
- Compute `sig = failure_breaker.signature(outcome["reason"])` before `record_failure` (so it's available for the hold decision and comment).
- Replace the `prior_streak + 1 >= MAX_CONSECUTIVE_FAILURES` check with `failure_breaker.should_hold(issue_number, repo, threshold)` where `threshold = (profile or {}).get("failure_threshold") or MAX_CONSECUTIVE_FAILURES`.
- `_park_stuck_ticket` → rename the added label from `needs-info` to `hold`; keep removing `ready-for-agent` + claim, keep the ordering (`hold` added before `ready-for-agent` removed — same reasoning as today's docstring, just the label changed); comment body now includes: the failure signature(s) that triggered it, and a generated `Revisit by: YYYY-MM-DD — <reason>` line. Add a small formatter next to the parsers it mirrors:
```python
# lib/ticket_policy.py, next to parse_revisit_comment
def format_revisit(date: str, condition: str | None = None) -> str:
    return f"Revisit by: {date}" + (f" — {condition}" if condition else "")
```
(keeps the generator and parser in the same module, in lockstep, per that module's own stated convention). **Default revisit window: 14 days from the park** — not specified by the ticket; I'm picking this as a defensible default (long enough the revisit/triage cycle isn't spammed, short enough it isn't forgotten) and making it a named constant (`DEFAULT_REVISIT_DAYS`) so it's a one-line change if Gil wants otherwise. Condition text names the repeat-signature case explicitly when that's why it stopped (`"same failure signature twice in a row"`) vs. the N-failures case (`"N consecutive pipeline failures"`), since that's the one piece a person re-triaging it actually needs to know.

**`lib/ticket_policy.py`**: add `"hold"` to `STATE_LABELS`.

**`lib/health_checks.py`**: rewrite `check_ticket_failure_streaks` to read `failure_breaker.ticket_streak()` instead of making a `gh issue view --json comments` call per claimed ticket (keeps the one `gh issue list` call for titles), and extend it to loop over `[REPO] + pp.dispatchable_repos()` (reusing the same helper `ticket_pipeline.py` already uses) so non-marvin profiled projects get the same early-warning instead of being silently uncovered as today. Add a new check, `check_held_by_retry_storm()`, reusing `should_hold()` across recent jsonl entries per project (no extra GH call at all) — green/informational (the breaker working as intended, not an alarm), listing ticket/project/signature/count, truncated at 5 like the other list-style checks. Wire both into `run_all()`.

**CONTEXT.md**: extend the "Ticket agents" / "Per-project execution profiles" sections — document the `hold`-on-N-failures rule, the `failure_threshold` profile field and its default, and that `Revisit by:` lines on these holds are machine-generated (distinct from a person's own hand-written hold).

## Tests to write first

From the ticket's own "Tests:" bullet (its de-facto break-it section, since none exists):
1. **N mixed failures** → held at exactly N, with distinct signatures recorded in the comment.
2. **2 identical signatures in a row** → held immediately even when N (e.g. 3) hasn't been reached.
3. **A success in between resets the count** → N-1 failures, then a success, then N-1 more failures does **not** hold (streak restarts from the success, not from zero historical failures).

Adversarial cases the section is missing, against the real collaborators (a real temp jsonl file via the existing `isolated_log` fixture pattern, a real `ticket_policy.parse_revisit_comment` round-trip on the generated comment — not a mock of either):

4. **Bad/malformed input** — a corrupt/unparseable line in `pipeline-failures.jsonl` between real entries must never crash the streak count or the hold decision (mirrors `_read()`'s existing per-line try/except; assert a corrupt line is skipped, not counted as a failure or a reset).
5. **Empty input** — no log file yet (first run ever on a machine) → streak 0, never held, never raises.
6. **Huge input** — thousands of historical lines across many unrelated tickets/projects (the exact #28-style 1,644-failure history already sitting in the real log shape) must not be O(n²) or re-count unrelated tickets; a ticket's own streak must only ever see *its* lines.
7. **Each dependency failing** — `gh issue edit`/`gh issue comment` failing (rate-limited, network down) while applying `hold` must not crash the run and must not re-queue the ticket as if it were still open for dispatch (mirrors the existing `test_a_failing_gh_call_never_stops_the_rest_of_the_park` pattern — same coverage needed for the new `hold`-adding call).
8. **Repeats/idempotency** — the same ticket crossing the hold threshold twice (e.g. revisited, re-dispatched, fails again immediately) must not double-apply `hold` or post two conflicting `Revisit by:` comments in a way `latest_revisit()` can't resolve (assert `latest_revisit` still picks the newest one cleanly).
9. **Concurrency** — two machines (mac-mini + macbook-pro) each running a different ticket for the *same* project write to their own per-machine `pipeline-failures.jsonl` (confirmed: `LOG_PATH` is per-machine, not shared) — assert the streak for ticket A on machine 1 is unaffected by ticket B's failures logged only on machine 2, and that cross-machine streak counting is **not** silently assumed (it isn't implemented; document that explicitly rather than let it look handled).
10. **Wrong permissions / env-not-ticket's-fault** — an `EnvMissing` or `TestTimedOut` outcome must **never** count toward the streak and must **never** trigger a hold (already true today via the no-strike/no-breaker-entry path; add a regression test that an env-missing run repeated N times in a row does not hold the ticket).
11. **Stale state** — a ticket already past N failures from *before* this change shipped (its real GH-comment history still has old `FAILURE_MARKER` comments but the jsonl log is the new counter) must not be instantly parked on the very next run off old comment history it no longer reads — assert the new counter starts from the jsonl log's own content, not from scraped comment history.
12. **A person's mistake** — a human manually removing `hold` and re-adding `ready-for-agent` on an already-held ticket (sending it back in) must get a **fresh** streak count (the next failure after re-release is failure #1 again, not an instant re-hold from stale pre-release jsonl lines) — this needs the streak function to reset on whatever signal means "a person restarted it," which is exactly why AC4's "success resets it" matters: if a person resends it and it succeeds, great; if they resend it and it fails again, the streak should still accumulate from the prior failures unless there's also a manual "clear" analogous to `failure_breaker.clear()`. **Open design question, not blocking**: should re-adding `ready-for-agent` to a held ticket implicitly reset its jsonl streak, or should a person need an explicit clear? I'll default to *not* auto-resetting (consistent with "verified, not assumed" — a label edit isn't proof the underlying cause was fixed) and document this as the behavior, with a test asserting it.
13. **Per-project isolation** — ticket #7 failing in marvin and ticket #7 failing in another profiled project must count as two independent streaks (mirrors the existing `test_ticket_7_in_two_projects_counts_as_two_tickets_not_one` pattern already proven for the cross-ticket breaker — same case needed for the per-ticket one).
14. **Profile override** — a project profile's `failure_threshold` (e.g. 5) is honored instead of the default 3; a profile with no `failure_threshold` key (or marvin, which has no profile file at all) falls back to the default; a profile with `failure_threshold: 0` or a negative number doesn't produce nonsensical behavior (hold immediately, or never divide/index out of range) — malformed-profile-value case.
15. **`STATE_LABELS` regression** — a ticket carrying only `hold` (no other state label, the exact shape this change produces) is **not** re-triaged back to `ready-for-agent` by `triage_verdict`/`plan_triage`, even with a fully-formed body. This is the latent bug this plan found and must close.
16. **Health check, all four branches** (mirroring `check_hold_revisit`'s own test shape once added): no data yet, stale, fresh+none held, fresh+N held (truncated at 5); malformed/missing jsonl log doesn't crash `run_all()`.
17. **Revisit round-trip** — the generated `Revisit by:` comment is byte-for-byte parseable by the existing `ticket_policy.parse_revisit_comment`/`latest_revisit` (a real round-trip, not asserting on the generator's output shape in isolation) — this is the "verify fails when code changes without a test changing" guard for this specific integration point, since `format_revisit` and `parse_revisit_comment` are two separate functions that must stay in lockstep.