## North-star fit

**Reuses before adding:** `auto_merge_shadow.pick_unscored` (lib/auto_merge_shadow.py:184) stays the single selection rule, just called in a loop instead of once; `mutation_check.merge_bodies`/`render_section` (lib/mutation_check.py:268-304) stay the one PR-body writer, generalized rather than duplicated; `error_log.record` (lib/error_log.py:92) is MARVIN's one existing "never silent" sink — wiring into it instead of inventing a second failure log; `disk_ledger.du_kb` (lib/disk_ledger.py:76) is the one existing bounded, TCC-safe disk-measurement primitive — reused instead of a second `du` wrapper; `_gh`'s existing `MARVIN_NO_TICKET` env (lib/auto_merge_shadow.py:256-263) is reused for the new PR write, not a second bypass. No new top-level file.

**Simplest sufficient:** one loop (`_score_many`) replaces one call (`_score_one`), one classifier function (`why_unscored`), one guarded write. No new background job, no new state file — the existing `~/.claude/logs/auto-merge-shadow.json` and its `_Locked` pattern carry the new fields.

**Tokens:** zero — this is pure Python/git/gh plumbing inside the existing hourly scan, no model calls.

**Capability, not passivity:** Gil currently has no visibility into *why* a PR is stuck unscored and no signal that the drain is working; this makes the system self-explaining (a stated cause on the PR, a real cost line in the step report) rather than something he has to go dig `~/.claude/logs` for, as I had to do to write this plan.

**Correcting the ticket's own assumption:** the ticket states "21 of 27 PRs are held only by mutation score pending" as of 2026-10-25. **That backlog no longer exists** — verified live: `gh pr list --repo G-Eskayo/marvin --state open` returns exactly 3 open PRs (#1273, #1264, #1256), and all three already carry a mutation score section. So AC1's "find out why" and AC2's "test reproduces the backlog" can't be satisfied by replaying the literal 21-PR incident; I did a code-level root-cause pass instead (below), and AC2's test reproduces the *mechanism* (same shape: N unscored PRs, hourly scans, a day's budget) rather than replaying dead data.

**Root cause, from reading the code (not guessing):**
- `_score_one` (lib/auto_merge_shadow.py:266-296) scores **exactly one** PR per call, and `run()` calls it once per hourly scan. Drain time for N unscored PRs is N hours — for 21 PRs that's 21h with *zero* slack for a skipped hour (mini asleep, disk full) or a retry, which is why "within one day" wasn't being met.
- Its `except Exception` (line 293) only `print`s to stderr — never `error_log.record` — so a failing scan (GH down, git lock, disk full) left no trace anywhere Gil would see it. This matches the ticket's "failing quietly" hypothesis directly.
- Nothing ever writes a reason onto the PR itself. A PR sitting unscored for days looks identical to one that's about to be scored next hour — AC1's literal ask ("write the cause into the PR") has no code path today.
- The local copy of `~/.claude/logs/auto-merge-shadow.json` I can read from this worktree has a `"scored": {}` map with only **2** entries ever recorded across the shadow's whole life, against `"seen": 26` PRs observed — consistent with the one-per-run rate being the bottleneck, though I can't read the mini's live log from here to confirm it's still behind today.
- `step(...)` (lib/ticket_pipeline.py:537) reports PR counts and the shadow verdict line, never a cost — AC4 has no code path either.

**Machine:** the scan runs where it runs today (the mini, per the module docstring) — no change.

## Decisions

<!-- marvin:decisions -->
### scan_budget: How much of each hourly scan should scoring get?
- [ ] A: 30 minutes wall-clock, however many PRs fit (≈3 at worst-case 10 min each — drains 21 in ~7 scans)
- [ ] B: 45 minutes wall-clock, however many PRs fit (≈4 at worst-case — drains 21 in ~5 scans)
- [ ] C: A fixed count cap instead of time (e.g. up to 5 PRs per scan, whatever time that takes)
- [ ] D: Leave it to the governor (ADR 0064) once it exists; hardcode 45 min for now as a placeholder

### stated_reason_channel: Where does "why still unscored" show up on the PR?
- [ ] A: A body section (like the existing Mutation Score section), via a generalized `merge_bodies`
- [ ] B: A single PR comment, posted once per cause and re-posted only if the cause changes
<!-- /marvin:decisions -->

## Tests (written first)

The ticket has no "How we'll try to break it" section, so these are drawn from AC3's explicit misuse list plus the north-star adversarial checklist, against `lib/tests/test_auto_merge_shadow.py`'s existing style (real tmp files, no mocking of `error_log`/`disk_ledger` themselves):

**Draining faster (AC2):**
1. One `_score_many` call scores several distinct unscored PRs (not just one) within a given time budget.
2. A simulated 21-PR backlog, run across repeated `_score_many` calls standing in for successive hourly scans, reaches zero unscored well inside a 24h budget-share — the literal "test reproduces the backlog and shows it drains."
3. A zero or already-exceeded budget scores nothing (no PR attempted) rather than erroring.

**Never stuck on one PR (AC2 + AC3's "crashing mutant run"):**
4. A PR whose scoring raises (simulated `run_mutation_check` exception) doesn't stop the same run from scoring the next unscored PR.
5. The same PR is not retried twice inside one run after failing once (so budget isn't wasted looping on one stuck PR), but **is** picked again on the *next* run (`pick_unscored` still finds it, since a failed attempt never writes to `scored`) — retried, never permanently skipped.

**Logged, never silent (AC3):**
6. A crashing mutant run is written to the real `error_log.jsonl` via `error_log.record(source="auto_merge_shadow", ...)` (assert against the actual file, not a mock), in addition to the existing stderr print.
7. A `subprocess.TimeoutExpired` from the git/gh calls is caught, logged the same way, and does not crash the run.
8. A PR that closes mid-scoring (the `gh pr edit` call fails because the PR is gone) is caught, logged, leaves no stale `scored` entry, and the run continues to the next PR.

**Stated cause on the PR (AC1):**
9. A PR open under 24h with no score yet gets no stated-reason write (too early to say anything useful).
10. Past 24h, a PR behind other older unscored PRs is classified "queued-behind-N".
11. Past 24h, a PR whose mutation check reports nothing-scoreable (mirrors `mutation_check.run_mutation_check`'s real "nothing could be scored" case) is classified "mutation-check-unavailable".
12. Past 24h, a PR with recent matching `error_log` entries is classified "repeated-failure"; otherwise "unknown".
13. The write is idempotent: calling it twice with the same cause+commit doesn't duplicate the section/comment; a changed cause or a new commit does re-fire it.
14. The write never produces a body that looks like a question to `bin/gh`'s Decisions gate (no `## Open questions`-shaped heading) — reusing a reporting-only heading.

**Cost stated (AC4):**
15. `run()`'s persisted state and the `_auto_merge_shadow` step line both carry a numeric wall-clock-seconds and a disk-KB (or `disk_ledger`'s real "not measured (...)" string) figure for the scan.
16. `disk_ledger.du_kb` returning its real "not measured" sentinel is surfaced as that string, not coerced to 0 or crashed on.

**Misuse / malformed input:**
17. A PR dict missing `headRefOid` or `body` doesn't crash `_score_many` or `why_unscored` (both already lean on `.get()` with defaults — this locks that in).
18. A corrupt shadow state file during a scoring run fails closed (extends the existing `test_a_corrupt_state_file_...` pattern to the new scoring path specifically).

## Task List

1. `lib/error_log.py`: no change needed — reuse `record()` as-is.
2. `lib/auto_merge_shadow.py`: refactor `_score_one` into `_score_many(prs, repo, path, budget_sec)` — loops `pick_unscored` (excluding this-run attempted-and-failed URLs) until `budget_sec` is spent; wire `error_log.record(source="auto_merge_shadow", ...)` into its exception handler (keep the stderr print); wrap it with `time.time()` and `disk_ledger.du_kb(scratch, timeout=...)` on each scratch worktree just before removal; persist `{"elapsed_sec", "scored_count", "disk_kb_or_reason"}` as `last_scan_cost` in state.
3. `lib/auto_merge_shadow.py`: add `last_scan_cost(path=STATE_PATH) -> dict` reader.
4. `lib/auto_merge_shadow.py`: add `why_unscored(pr, now, scored, error_log_entries)` — None under 24h open; else "queued-behind-N" / "mutation-check-unavailable" / "repeated-failure" / "unknown".
5. `lib/mutation_check.py`: generalize `merge_bodies(current_body, new_section, start_marker=..., end_marker=...)` with today's markers as defaults *(only if Decision `stated_reason_channel` picks A)*.
6. `lib/auto_merge_shadow.py`: add the idempotent stated-reason write per the `stated_reason_channel` decision, guarded by a `reason_stated` flag (cause + commit) in shadow state.
7. `lib/ticket_pipeline.py:_auto_merge_shadow`: extend the `step(...)` line with the cost from `last_scan_cost()`.
8. Write tests 1–18 above in `lib/tests/test_auto_merge_shadow.py` first; confirm each fails against current code; then implement steps 2–7 to pass them.
9. Update `lib/auto_merge_shadow.py`'s module docstring and `CONTEXT.md`'s Auto-merge section (§ designed 2026-10-09, ADR 0064) with the decided `scan_budget` and a real measured per-scan cost, replacing the "each check can take 10 minutes" line.
10. Run the full test suite plus the new tests; do **not** run a real scoring pass against live GitHub inside this session — the prior two attempts both hit a 900s launcher timeout partly from doing exactly that (#1180/#1181 are the actual launcher-timeout tickets, per the issue's needs-info-sweep comment). The merged code drains whatever backlog exists on the next real hourly scan.
11. `graphify update .` after the code changes.