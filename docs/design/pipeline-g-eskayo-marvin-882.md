## North-star fit

**Reuses before adding anything new:**
- `run_ticket.py:build()`'s existing `except TestTimedOut` handling (`lib/run_ticket.py:329-334`) and `settle()`'s `timed_out` branch (`lib/run_ticket.py:387-405`) — the new "evidence timed out after passing" path is a sibling branch of the exact same shape, reusing `_retry_line`, `_feed_breaker`, `_release_claim`, `_trigger_redispatch` unchanged.
- `sandbox_orchestration._doc_slug`/`_branch_for` (`lib/sandbox_orchestration.py:391-397`) already compute the *deterministic* worktree path for a `ticket_ref` — reused (via a new 3-line `worktree_path_for()`) instead of inventing a second naming scheme.
- `cleanup_sweep.decide_worktree` (`lib/cleanup_sweep.py:476-500`) already has a "claimed (running) → keep" branch; the fix is one more early-return of the same shape, not a new sweep.
- `mr_raiser._format_dev_evidence`'s existing `{"na":, "error":}` shape (`lib/mr_raiser.py:157-170`) is reused verbatim for `test_results` instead of inventing a second "couldn't capture" convention.
- `purpose_metrics.RATES`/`MEASURES` (`lib/purpose_metrics.py:142-148,568-569`) and the ticket-stage-scanning pattern already used by `_prd_dispatches`/`_pipeline_verify_timeouts` (`lib/purpose_metrics.py:197-250`) are reused for the new purpose metric; the "one Mac measures a global GitHub fact" gating already established for `incident_ladder` (`lib/purpose_metrics.py:559-560`, `OUTCOME_CHECK_MACHINE` in `lib/cleanup_sweep.py:696`) is reused for the merged-PR count so it isn't multiplied across Macs.
- The decisions-format convention (`docs/agents/decisions-format.md`) for the one genuine open fork below.

**Why this is the simplest sufficient approach:** no new CLI flag, no new dispatch path, and no change to the claim/scan machinery. `run_ticket.py <n>` is invoked exactly as today; `build()` itself checks, before touching git, whether a durable marker says "this ticket's worktree already has passing code waiting on evidence." Everything downstream (claim, backoff comment, redispatch) is the *existing* unclaimed-ready cycle. This is "elegant sufficiency": the one new primitive is a small JSON marker inside the worktree's own `.git/` directory (never committed, dies with the worktree, lives only on the machine that holds it).

**Where it spends/saves:** removes the dominant cost in the pipeline (a full agent plan+build) for exactly the case the ticket measures — a build whose code already passed. Spends a little: one extra `git rev-parse`/fetch per resume to detect staleness, and one JSON file read/write per evidence attempt. Net: large token/compute savings (north star 1), nothing new for a human to babysit.

**Phone-OS direction:** more reliable, OS-shaped background work — a transient step failure no longer discards finished work. No change to reachability/surfacing.

**More capable or more passive:** purely internal; the owner's only visible change is PRs that previously silently vanished (full rebuild, same timeout, repeat) now land, sometimes with an honest "evidence not captured" note instead of nothing. More capable (faster, truthful signal), never more passive.

**Ticket's own stated fit, checked against the code:** accurate on "doesn't change how tests are chosen/how long they're allowed." One correction: the ticket's own "Check on: 2026-11-13" date has already passed (today is 2026-11-26). `purpose_metrics.outcome_gap()` (`lib/purpose_metrics.py:842-850`) explicitly treats an already-past check-on date as a gap ("the check would measure before the fix ran"), so the PR must carry a **freshly computed** Check-on date (e.g. merge date + 7 days), not the ticket's original text verbatim.

---

## Why the literal architecture rules out a naive "just retry" fix

`sandbox_orchestration._create_worktree` (`lib/sandbox_orchestration.py:464-489`) is **destructive on every call**: it force-removes any pre-existing worktree/branch of the same name (after rescuing it to `refs/rescue/...`) and recreates it fresh from `origin/<base_branch>`. So a resume path must *never* call `execute_ticket()` again — it has to intervene in `build()` **before** `execute_ticket` is invoked, operate on the existing worktree directly, and only fall through to a normal `execute_ticket()` call when there's nothing valid to resume.

Also: `raise_mr`/`_commit_and_push` (`lib/mr_raiser.py:87-107`) is what pushes the branch — and it only runs *after* a successful evidence capture. So when evidence times out, the branch has **never been pushed**. "Retry on the other Mac" therefore cannot mean "the same worktree, elsewhere" unless the branch is also pushed somewhere on timeout — this is a real fork, captured as Decision 2 below.

---

## Design

1. **`lib/sandbox_orchestration.py`**: add `worktree_path_for(ticket_ref: str) -> Path` = `WORKTREES_ROOT / _doc_slug(ticket_ref)` (pure, reuses `_doc_slug`). No behavior change to `_create_worktree`.

2. **`lib/evidence_capture.py`**: add a small, tolerant marker API (lives next to `TestTimedOut`, which it exists to recover from):
   - `pending_evidence_path(worktree_path) -> Path` → `worktree_path / ".git" / "marvin-evidence-pending.json"` (inside `.git/`, so `git add -A` in `mr_raiser._commit_and_push` never commits it, and it disappears automatically if the worktree is ever removed).
   - `read_pending_evidence(worktree_path) -> dict | None` — returns `None` on missing file, bad JSON, wrong types, or an entry older than `PENDING_EVIDENCE_MAX_AGE_H = 48` (reusing `cleanup_sweep.BACKUP_MIN_AGE_HOURS`'s existing threshold as precedent) — never raises.
   - `write_pending_evidence(worktree_path, **fields) -> None` — writes `{"ticket_ref", "base_branch", "base_sha", "attempt", "reason", "created_at", "final_comparison", "code_review_notes"}` (enough to reconstruct the `execution_result` dict `raise_mr` needs). Best-effort: a write failure (full disk, permissions) is logged and swallowed, falling back to the "no marker" path next time.
   - `clear_pending_evidence(worktree_path) -> None` — `missing_ok=True` unlink.

3. **`lib/run_ticket.py`**:
   - Extract the current post-`result["passing"]` block (test_results/dev_evidence computation + `raise_mr` call) into `_raise_with_evidence(ticket_ref, result, profile, measurer, marvin_measure, attempt=1) -> dict` (the existing `outcome = raise_mr(...)` return). Wrap only this function's test-results computation in `try/except TestTimedOut`.
   - On success inside `_raise_with_evidence`: `clear_pending_evidence(result["worktree_path"])`, return the normal outcome.
   - On `TestTimedOut`: if `attempt < MAX_EVIDENCE_RETRIES` (new constant, **3** — chosen so the ticket's own "times out twice, then succeeds" case is covered by default, see note below): `write_pending_evidence(...)`, return `{"raised": False, "pr_url": None, "reason": str(exc), "evidence_timed_out": True}`. If `attempt >= MAX_EVIDENCE_RETRIES`: build `test_results = {"na": False, "error": f"couldn't capture: {exc}"}`, still attempt `dev_evidence` fresh (unchanged, already-graceful call), call `raise_mr` with that `test_results`, `clear_pending_evidence(...)`, and return the normal (now `raised: True`) outcome — **this is the one path that never needs settle() to know anything special**.
   - `build()`: before calling `execute_ticket`, call a new `_resume_pending_evidence(ticket_ref, repo, profile) -> dict | None`:
     - compute `wt = worktree_path_for(ticket_ref)`; if it doesn't exist on disk → `None` (fall through to a normal build, after `ts.record_stage(..., "executing", "failed", "a pending evidence retry's worktree was gone; rebuilding")` for visibility).
     - `marker = read_pending_evidence(wt)`; `None` → fall through to normal build.
     - if a PR already exists for the marker's branch (reuse the same `gh pr view <branch>` lookup `mr_raiser._default_open_pr`'s "already exists" path already performs; call it once here defensively) → `clear_pending_evidence(wt)`, return a synthetic "already raised" outcome so `build()` doesn't duplicate work.
     - check staleness: `git -C wt fetch origin <base_branch>` then compare `git rev-parse origin/<base_branch>` to `marker["base_sha"]`. Unreadable (git failure) → treat as stale (fail safe, never resume against unknown state).
       - **not stale** → reconstruct `result = {"passing": True, "worktree_path": wt, "final_comparison": marker["final_comparison"], ...}` and call `_raise_with_evidence(ticket_ref, result, profile, measurer, marvin_measure, attempt=marker["attempt"] + 1)` directly — this *is* the resumed build's outcome.
       - **stale** → resolved by Decision 1 below; whichever option is NOT chosen, the losing path is: `clear_pending_evidence(wt)`, `ts.record_stage(..., "executing", "failed", "its base branch moved; rebuilding")`, fall through to a normal `execute_ticket()` call.
   - `settle()`: add an `elif outcome.get("evidence_timed_out")` branch, structurally identical to the existing `timed_out` branch (`lib/run_ticket.py:387-405`) but: new `EVIDENCE_TIMEOUT_MARKER = "Evidence capture timed out; code already passed, worktree kept for a quick retry"` comment text (reusing `_retry_line`), `ts.record_stage(issue_number, "verifying", "failed", f"evidence capture timed out: {reason}")` (kept on stage `"verifying"` deliberately, so `purpose_metrics._pipeline_verify_timeouts` — which already reads `stage == "verifying"` + `"timed out"` in `detail` — keeps working with **no change**), `_feed_breaker(...)` (not exempt — same reasoning as plain `timed_out`), `_release_claim(...)`, `_trigger_redispatch()`. No park path here — exhaustion is handled inside `build()`/`_raise_with_evidence`, never reaches `settle()` as a distinct terminal state.
   - `BREAKER_EXEMPT` stays unchanged (`evidence_timed_out` is *not* exempt, matching `timed_out`).

4. **`lib/cleanup_sweep.py`**: `decide_worktree()` gets one new early branch, right after the `in_use` check:
   ```python
   if _has_pending_evidence(wt["path"]):
       return "keep", "a pending evidence retry is waiting on it"
   ```
   where `_has_pending_evidence` calls `evidence_capture.read_pending_evidence` (new import). This is the explicit, tested guarantee the ticket asks for, independent of claim state or age.

5. **`lib/mr_raiser.py`**: `_format_test_results` gets one new branch, mirroring `_format_dev_evidence`'s existing `error` convention:
   ```python
   if test_results and test_results.get("error"):
       return f"⚠ **Test evidence couldn't be captured:** {test_results['error']}"
   ```
   placed before the existing `"Not available."` fallback.

6. **`lib/purpose_metrics.py`**: add
   - `_planning_starts(stages_dir=None, days=PROBE_WINDOW_DAYS, now=None)` — mirrors `_prd_dispatches`'s exact iteration pattern (`lib/purpose_metrics.py:197-218`), counting `stage == "planning", status == "started"` events in the window. No machine-gating needed (ticket-stage counts are already correctly additive across Macs, as `_prd_dispatches`/`_replanned_tickets` already assume).
   - `_merged_marvin_prs(days=PROBE_WINDOW_DAYS, now=None)` — `gh_env.run(["gh","pr","list","--repo","G-Eskayo/marvin","--state","merged","--search", f"merged:>={cut_date}"])`, counted — gated to run for real only on `OUTCOME_CHECK_MACHINE` ("mac-mini-1", reusing the exact `_is_pull_only`-adjacent convention at `lib/cleanup_sweep.py:696-707` and `lib/purpose_metrics.py:559-560`'s comment about `incident_ladder`), returning `0.0` elsewhere so `measure_everywhere`'s cross-Mac sum isn't multiplied.
   - `MEASURES.update({"planning-starts-7d": lambda: _planning_starts(), "marvin-prs-merged-7d": lambda: _merged_marvin_prs()})`
   - `RATES["agent-builds-per-merged-pr"] = ("planning-starts-7d", "marvin-prs-merged-7d")`

7. **ADR**: write `docs/adr/0086-evidence-only-retry-keeps-the-worktree.md` recording: the marker-in-`.git/` mechanism, why `execute_ticket` can never be re-entered for a resume, the `decide_worktree` guarantee, and the chosen answers to Decisions 1 and 2 below. (Next free ADR number confirmed: 0086.)

---

## Decisions
<!-- marvin:decisions -->
### stale_base: The worktree's base branch (main) has moved since the passing build. How should the retry handle it?
- [ ] A: Rebase the kept worktree onto the new base and rerun verify+evidence before raising the PR (consistent with the merge gate's own "behind + shares files → rebase, retest" rule, ADR 0026; costs a rebase-conflict fallback path)
- [ ] B: Treat it as stale — discard the pending-evidence marker and do a full rebuild against the new base (simpler, never risks reviewing against a base nobody verified against, but gives up the "finished build" savings exactly when main is busiest)

### cross_machine_resume: The ticket says the retry can run "at a quiet moment... or on the other Mac." Since the branch is never pushed until evidence succeeds, a worktree genuinely can't move to another Mac without an extra push. Which should this build?
- [ ] A: On every evidence timeout, also push the branch to a scratch ref (e.g. `evidence-retry/<branch>`) so a different Mac could, in principle, fetch and resume it — more moving parts, a scratch-ref cleanup obligation, and `mr_raiser`'s "already exists" PR-dedupe logic needs a look to make sure a scratch push never confuses it
- [ ] B: Same-machine-only resume for now. If the ticket's claim is released and a *different* Mac happens to pick it up before the original Mac retries, that Mac just does a normal full rebuild (strictly cheaper than today's baseline, just not a literal "resume"); "the other Mac" language in the ticket is corrected to describe this fallback rather than a true relocation

### evidence_retry_cap: How many consecutive evidence-only timeouts before giving up and opening the PR with "couldn't capture" instead of retrying again? (optional)
- [ ] A: 3 (covers "times out twice, then succeeds" with one retry to spare)
- [ ] B: 5 (match `MAX_CONSECUTIVE_RETRIES`, the existing general retry cap)
- [ ] C (text)
<!-- marvin:decisions-end -->

*(Plan below assumes Decision `stale_base` = B and `cross_machine_resume` = B as the simplest sufficient defaults if left unanswered at build time per CLAUDE.md's autonomous-call rule — but since this ticket is `ready-for-agent`, not yet answered, the PR will carry the Decisions block rather than guess silently on something this architecturally visible.)*

---

## Tests to write first

Mapped to the ticket's "How we'll try to break it" list, plus the required misuse categories:

1. **Evidence times out twice, then succeeds → one build, one PR.** `test_run_ticket.py`: `execute_ticket` mocked to run exactly once (assert call count == 1) while two successive calls into `_raise_with_evidence`'s wrapped test-results step raise `TestTimedOut`, the third succeeds; assert `raise_mr`/PR-opening is called exactly once at the end, with `attempt == 3` in the final call, and that `build()` never calls `execute_ticket` on the 2nd/3rd attempts (resumed from the marker instead).
2. **Evidence never finishes → PR opens with the "couldn't capture" note, no test-count claims.** `test_mr_raiser.py`: `_format_test_results({"na": False, "error": "..."})` renders the literal "Test evidence couldn't be captured" sentence and no passed/failed/total numbers. `test_run_ticket.py`: after `MAX_EVIDENCE_RETRIES` consecutive `TestTimedOut`s, `raise_mr` is still called (outcome `raised: True`), marker cleared, no park.
3. **Worktree deleted by a disk sweep between attempts → falls back to a rebuild, with a stage note.** `test_run_ticket.py`: `_resume_pending_evidence` with a worktree path that doesn't exist on disk returns `None` and a `"executing"/"failed"` stage note is recorded before the normal `execute_ticket()` path runs.
4. **The sweep must never delete a worktree holding a pending evidence retry.** `test_cleanup_sweep.py`: `decide_worktree` returns `("keep", ...)` for a worktree with a fresh marker file regardless of `claimed`, `dirty`, `ahead`, or `age_hours` (including `age_hours > BACKUP_MIN_AGE_HOURS`, which today would otherwise trigger `"backup"`/removal).
5. **Base branch moves on before the retry.** `test_run_ticket.py`: marker's `base_sha` != current `origin/<base_branch>` tip → handled per the chosen Decision (rebase+retest, or marker cleared + stage note + fallback to full rebuild) — never silently resumed against a base nobody checked.
6. **Ticket closed by someone else meanwhile → no PR.** `test_run_ticket.py`: marker present, but `gh pr view <branch>` already returns an existing PR (or the issue is `CLOSED`) → `build()` clears the marker and returns a no-op outcome, never a duplicate PR, never a crash.
7. **Malformed/corrupt marker.** `test_evidence_capture.py`: `read_pending_evidence` returns `None` for missing file, truncated/invalid JSON, wrong types, and an entry older than 48h — never raises.
8. **Unwritable/unreadable marker (disk full, permissions).** `test_evidence_capture.py`: `write_pending_evidence` swallows an `OSError` and logs; a subsequent `read_pending_evidence` behaves exactly as "no marker" (full rebuild next time), never crashing the run.
9. **Each dependency failing.** `test_run_ticket.py`: `git fetch`/`git rev-parse` failing during the staleness check is treated as "stale" (fail safe), never as "fresh."
10. **Repeats/concurrency.** `test_cleanup_sweep.py`/`test_run_ticket.py`: a second concurrent read of the same marker (simulating two near-simultaneous dispatches before the existing claim mechanism serializes them) never double-raises a PR — reuse `mr_raiser`'s existing "already exists" tolerance; add a regression test asserting it still applies when the second caller arrives via the resume path.
11. **A person's mistake / stale state.** `test_run_ticket.py`: a marker whose `attempt` field was hand-edited or missing is treated as `attempt = 1` (never crashes, never silently skips the cap).
12. **Breaker accounting unchanged.** Extend `test_run_ticket.py`'s existing `_outcome_kinds()`/`test_every_non_success_outcome_feeds_the_breaker_unless_it_is_a_named_exception` parametrization (`lib/tests/test_run_ticket.py:1229-1268`) with an `"evidence_timed_out"` kind (code already passed, then `TestTimedOut` on the evidence step) and assert it is **not** in `BREAKER_EXEMPT` and **does** feed the breaker.
13. **`_pipeline_verify_timeouts` probe unaffected.** `test_purpose_metrics.py`: a `"verifying"/"failed"` stage event with the new evidence-timeout detail text still counts, since detail still contains "timed out."
14. **New purpose metric.** `test_purpose_metrics.py`: `_planning_starts` counts `planning/started` events correctly from a fixture `stages_dir` over the 7-day window (reusing `_prd_dispatches`'s existing fixture style); `_merged_marvin_prs` returns `0.0` when `machine_profile.registry_id()` isn't the designated host, and the real count when it is (mocked `gh_env.run`); `RATES["agent-builds-per-merged-pr"]` computes the ratio via `_rate`.
15. **Fresh Check-on date.** `test_purpose_metrics.py` or a `fit_check`/ticket-template test: `outcome_gap()` does not flag a gap when the PR's Purpose-metric block carries a Check-on date computed at merge time (not the ticket's original, now-past, 2026-11-13).

---

## Task List

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