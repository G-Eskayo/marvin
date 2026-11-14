## North-star fit

**Reuses before adding anything new:**
- `record_author_ramps(repo, rules, gh=None, ramp_path=None, …)` in `lib/auto_merge_shadow.py:227` already has the exact seam this ticket needs — a real collaborator with an injectable override — for testing GitHub calls without touching the network. The new scoring loop copies that idiom (`clone_and_score=None` defaulting to a real implementation) instead of inventing mocks or patching `sys.modules`.
- `error_log.record(source, message, raw=…)` (`lib/error_log.py:92`) is the one standing "never silent" channel (marvin#422) — reused as-is for scoring failures, no new log file.
- `disk_ledger.du_kb(path, timeout=…)` (`lib/disk_ledger.py:76`) is reused as-is to cost the scratch worktree before it's removed.
- `mutation_check.render_section` / `merge_bodies` (`lib/mutation_check.py:268,292`, "the reviewed engine, PR #351") are reused **unchanged** for every "cause written into the PR" case — scored, unmeasurable-with-reason, and the 24h safety-net note all go through the same marker/section, so there's one channel, not three.
- The monkeypatch idiom already in `lib/tests/test_ticket_pipeline.py:1574` (`monkeypatch.setattr(tp, "_run_ticket_agents", …)`) is reused for the new decoupling regression test.

**Why this is the simplest sufficient approach:** the ticket's own prior attempts (see below) tried to generalize `mutation_check.merge_bodies` with new marker params and touch the mutation engine itself — both unnecessary once you look at what's actually broken. The fix is confined to `auto_merge_shadow.py` plus a 2-line move in `ticket_pipeline.py`; `mutation_check.py` is **not touched at all**, including the one line I initially suspected was a bug (it isn't — see Investigation).

**Where it spends/saves tokens:** no real scoring pass runs during implementation (that's what timed out twice before); tests inject fake `gh`/`clone_and_score` collaborators so the suite stays fast. The fix itself *reduces* ongoing cost: today's code reprocesses nothing extra, so there's no added resource burn, only correctness and throughput.

**Phone-OS / capability:** this doesn't touch anything user-facing; it makes an existing promise (every PR gets judged, nothing silent) actually hold, which is a precondition for switching auto-merge on at all (north star 2's reliability precondition) and for #343.

**Machine:** unchanged — runs where it already runs, on the mini, inside the existing hourly `_scan`.

**More capable or more passive:** more capable — Gil currently has to notice on his own that a PR has been silently stuck; after this, the PR itself says why, and the shadow report stops lying ("pending" when the real answer is "will never get a score, by design").

## Investigation ("find out why" — done now, not guessed)

Read the live `~/.claude/logs/auto-merge-shadow.json` and several real PR bodies on GitHub (read-only `gh pr view`). Three concrete, verified causes, not a hypothesis:

1. **Head-of-line blocking.** `_score_one` (`lib/auto_merge_shadow.py:266`) scores **at most one** PR per `run()`, always the globally-oldest unscored one (`pick_unscored`). If that PR's scoring throws, the exception is swallowed (`except Exception: print(..., file=sys.stderr)`) and **nothing else is attempted that cycle** — the same PR is retried next hour, blocking every newer PR behind it. `scored` in the live state file has only ever recorded 2 PRs total despite 8+ recorded runs for that cohort — consistent with this.
2. **A real single point of failure.** `_auto_merge_shadow(step)` (`lib/ticket_pipeline.py:511`) is called *inside* `_run_ticket_agents`'s one `try` block, **after** `ticket_agents.load_config/collect/run` (lines 499–508). If any of those throw, `_auto_merge_shadow` never runs that cycle at all, folded into one generic `"Ticket agents: skipped: {e}"` — mutation scoring silently stops whenever an unrelated subsystem breaks.
3. **A messaging bug, not an engine bug.** Confirmed on live PR #592 (merged): its real GitHub body **already contains** the true cause — `Score: unknown (nothing could be scored (see unmeasured)). ... - not measured: dashboard/... JS isn't mutation-tested yet` for each file — written by the existing, reviewed `render_section`. But `auto_merge_shadow.verdict()` (`lib/auto_merge_shadow.py:58-62`) only ever checks for a *numeric* score; when there isn't one it always says the generic `"mutation score pending (its tests haven't been checked by planting bugs yet, #339)"`, even when scoring already ran and the PR is **structurally never going to get a number** (no JS mutation engine exists — confirmed intentional by the passing test `test_js_changes_are_unmeasured_for_now_never_scored`, `lib/tests/test_mutation_check.py:338`, and the module's own docstring). I checked this specifically because it looked like a bug in `mutation_check.py` — it isn't; changing that engine would contradict an existing, deliberately-written, passing test, which is exactly the kind of change a code review should (and, per the ticket's history, did) flag as must-fix. **`mutation_check.py` gets no changes in this plan.**

Also verified: no scan ever measures or reports time/disk cost (AC4 — nothing to fix there but to add), and PR #984 (merged, real score 25% on GitHub) sits in the local shadow cache frozen at `score: null` from the one run that first saw it — further evidence the scanner has gone stretches without running at all, consistent with cause 2.

## Decisions
<!-- marvin:decisions -->
### scan_budget: How much wall-clock time should one hourly run spend scoring PRs?
- [ ] A: 10 minutes (today's implicit ~1-PR assumption)
- [x] B: 30 minutes (drains the current ~15–20 PR backlog within a few hours) — chosen 2026-11-11
- [ ] C: 45 minutes (fastest drain; still leaves the hour's remaining time for the rest of the scan)
- [ ] D: No fixed ceiling — keep scoring every run until nothing at its current commit is left unscored

### js_only_gate: A PR with no Python changes can never get a numeric mutation score (no JS engine exists). What should that mean for auto-merge, now that the real cause is reported instead of "pending"?
- [ ] A: Keep asking forever — Gil always approves these by hand until a JS mutation engine exists (today's behavior, now reported honestly)
- [x] B: Treat "no Python changed" as exempt from the mutation gate — such a PR can auto-merge on its other checks alone — chosen 2026-11-11
- [ ] C: Exempt only inside owned areas under a size cap (e.g. dashboard-only, < 300 changed lines); anything bigger still asks
<!-- /marvin:decisions -->

## Tests first (write these before any implementation code; each must fail against current code first)

**`lib/tests/test_mutation_check.py` — none.** Confirmed by investigation that no change belongs here; the existing `test_js_changes_are_unmeasured_for_now_never_scored` stays green, unmodified.

**`lib/tests/test_auto_merge_shadow.py` (extend):**
1. `mutation_reason(body)` extracts the "unknown (...)" explanation already written by `render_section`, including the per-file "JS isn't mutation-tested yet" detail; returns `None` when no mutation-check section exists at all.
2. `verdict()` reports the real reason (e.g. "JS isn't mutation-tested yet") instead of generic "pending" when a body already has an "unknown" section; still says "pending" when the section is wholly absent (never attempted).
3. `_score_many` with a budget big enough for 3 fake scorings scores all 3 oldest-first PRs, recording each in `scored`.
4. A budget that only covers 1 scoring stops after it — bounded cost.
5. **Head-of-line regression test:** the oldest unscored PR's injected `clone_and_score` always raises; `_score_many` still scores the next-oldest PRs in the *same* run. Must fail against today's `_score_one`.
6. A scoring failure calls `error_log.record(source="auto_merge_shadow", …)` (mocked) and still prints to stderr.
7. A scoring failure writes a "could not run the mutation check: <reason>" section into the PR body via the injected `gh` (cause visible on the PR itself, AC1).
8. The same persistent failure on a later run (same PR, same commit) does not re-edit an unchanged reason (idempotent) but does retry the scoring attempt.
9. An exception raised mid-mutation-check (simulated hang/crash) is caught per-PR; remaining PRs in the batch still get attempted.
10. A PR closed mid-scoring (injected `gh` raises "no such pull request") is logged and skipped, not left half-written.
11. Two pushes to the same PR between pick and write (headRefOid changes mid-run) don't corrupt `scored`; the stale-score invalidation (`pick_unscored`) still re-catches it on a later run.
12. Running `_score_many` twice back-to-back with nothing new unscored does nothing destructive and returns `scored: 0`.
13. `_score_many`'s return includes `elapsed_sec` and `disk_kb`, aggregated from an injected disk-cost collaborator, including the "not measured (protected/timed-out)" sentinel handled as 0, not crashing.
14. A PR open > 24h with no score and no existing "unknown" reason gets exactly one "still queued" note written; a PR under 24h old gets none yet.
15. A PR already carrying a numeric score or an "unknown: …" reason is excluded from the 24h safety net even if older than 24h (never overwrites real information with a generic note).
16. `run()`'s `step(...)` line and persisted `last_report` include the measured time/disk cost text (AC4, checked as a literal field/string, not just "code ran").
17. A PR body containing adversarial markdown that mimics the mutation-check markers (an author pastes `<!-- /marvin:mutation-check -->` into their own description) doesn't corrupt the splice — regression test on existing `merge_bodies` behavior now exercised through the new write paths.
18. One small, real, local-only integration test: a tiny real git repo in `tmp_path` with one real Python change, exercising the actual (non-injected) `_clone_and_score` end to end (fetch/worktree/`run_mutation_check`/remove/`du_kb`) — bounded to a few seconds, never touching the live mini state or the live 21-PR backlog.

**`lib/tests/test_ticket_pipeline.py` (extend):**
19. **Decoupling regression test:** `ticket_agents.load_config` (or `.collect`/`.run`) raises; assert `auto_merge_shadow.run` (mocked) is still invoked from `_scan`. Must fail against today's code (call is inside the same try as the raising code).

## Task List

1. `lib/auto_merge_shadow.py`: add `mutation_reason(body) -> str | None`; update `verdict()` to use it instead of the generic "pending" message when a reason already exists.
2. `lib/auto_merge_shadow.py`: extract `_clone_and_score(pr, repo, *, gh=None) -> dict` from today's `_score_one` (unchanged git/gh/`mutation_check` logic, plus `disk_ledger.du_kb` cost measurement before worktree removal), with the same injectable-collaborator idiom as `record_author_ramps`.
3. `lib/auto_merge_shadow.py`: replace `_score_one` with `_score_many(prs, repo, path, budget_sec=<decided scan_budget>, *, gh=None, clone_and_score=None, now=None)` — budgeted loop, per-PR isolation (one failure never blocks the rest of that run), `error_log.record` on every failure (stderr print kept), idempotent "could not run: …" body write on failure, returns a cost summary (`elapsed_sec`, `disk_kb`, `scored`, `failed`).
4. `lib/auto_merge_shadow.py`: add the 24h stuck-queue safety net inside `run()` — any open PR older than 24h with no score and no existing "unknown" reason gets one "still queued" note written, using the same `render_section`/`merge_bodies` channel.
5. `lib/auto_merge_shadow.py`: update `run()` to call `_score_many` with the decided budget, fold its cost summary into `last_report`, and extend `ticket_pipeline._auto_merge_shadow`'s `step(...)` line to state the measured time/disk cost (AC4).
6. `lib/ticket_pipeline.py`: move `_auto_merge_shadow(step)` out of `_run_ticket_agents`'s `try` block (delete line 511) to its own statement in `_scan`, immediately after `_run_ticket_agents(step, summary)` (after line 933) — it already has its own internal try/except.
7. Write all 19 tests above first in `lib/tests/test_auto_merge_shadow.py` and `lib/tests/test_ticket_pipeline.py`; confirm tests 5 and 19 fail against current code, then implement steps 1–6 to make everything pass.
8. Update `lib/auto_merge_shadow.py`'s module docstring and `CONTEXT.md`'s Auto-merge section with the decided `scan_budget`, the measured per-scan time/disk cost, and the `js_only_gate` decision, replacing the vague "each check can take 10 minutes" line.
9. Run the full Python test suite locally. Do **not** run `auto_merge_shadow.run()` against the real live backlog in this session (the prior two attempts timed out doing exactly that) — the fix drains it for real on the mini's next scheduled hourly scan.
10. `graphify update .` after the code changes.