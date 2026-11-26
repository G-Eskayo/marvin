## North-star fit

**Reuses, before adding anything new:**
- `mr_raiser._commit_and_push` (`lib/mr_raiser.py:87`) — exposed as a small public wrapper and called *earlier* (right after `result["passing"]` is True), instead of inventing a new push mechanism. Pushing the branch is what makes "keeps its worktree and branch" literal and machine-independent, since GitHub is already the pipeline's one shared truth (`docs/life-of-a-ticket.md`, "The architecture: what runs where").
- `ticket_policy.retry_marker` / `retry_not_before` / `run_ticket._retry_line` (`lib/ticket_policy.py:114-156`, `lib/run_ticket.py:52-58`) — the existing hidden-HTML-comment-on-the-issue idiom for "try again, not before `<time>`, read identically by both Macs." Reused for the new evidence-pending state instead of a new state store.
- `run_ticket._trailing_streaks` (`lib/run_ticket.py:116-139`) — extended to count a third marker kind rather than writing a parallel counter.
- `sandbox_orchestration._design_doc_path` / `_task_list_path` (`lib/sandbox_orchestration.py:400-409`) — the existing "artifact lives inside the worktree, travels with the branch" pattern, reused for a small sidecar JSON that carries `final_comparison` across the evidence-only retry (which never calls `execute_ticket` again, so it has no comparison dict of its own).
- `cleanup_sweep.decide_worktree` / `is_claimed` wiring (`lib/cleanup_sweep.py:476-549`) and `purpose_metrics._replanned_tickets` (`lib/purpose_metrics.py:173-194`) — both extended in place, not duplicated.
- `evidence_capture.TestTimedOut` / `capture_test_results` / `capture_dev_evidence` — unchanged; only *where* they're called and *how the timeout is handled* changes.

**Why this is the simplest sufficient shape:** the bug is that `build()` treats a `TestTimedOut` raised *after* `result["passing"]` is True identically to one raised *during* the tune loop (`lib/run_ticket.py:329-334`, `lib/sandbox_orchestration.py:522`/`527`/`563`). The fix only needs to split that one `except` into two paths and give the post-passing path somewhere safe to park (origin, via an existing push function) and a way to be picked up again without planning (a new CLI entry point that skips `execute_ticket` entirely). Nothing about test selection, timeouts, or the merge gate itself changes — exactly the boundary the ticket's own "North-star fit" draws, and it checks out against the code.

**Resources:** removes exactly the waste named in the ticket — a full agent planning+build run (the most expensive thing the pipeline does) for code that already passed. Spends a little: one extra `git push` per passing build (cheap), and a worktree is held open slightly longer across machines than today (bounded by the same backoff/cap machinery already in use).

**Phone-OS direction:** neutral — this is pipeline plumbing, not a user-facing surface.

**User capability:** leaves Gil **more free**, not more passive — this is a system efficiency fix (stop burning rebuilds), not automation of a judgment call he was making himself. No north star argues against it.

**Machine:** the fix runs wherever `run_ticket.py` already runs (Mac mini primary, laptop secondary) — no new machine requirement.

---

## What's actually broken (confirmed by reading the code)

`run_ticket.build()` (`lib/run_ticket.py:275-355`) calls `execute_ticket()` (which **always** wipes and recreates the worktree, `sandbox_orchestration._create_worktree`, `lib/sandbox_orchestration.py:432-489`, even preserving the old state under `refs/rescue/...` first) and, only if that returns `passing: True`, runs a **second, separate** evidence-capture step (`capture_test_results` fallback / `capture_dev_evidence`, `lib/run_ticket.py:311-323`) whose results go into the PR body. Both `execute_ticket()`'s own tune-loop test runs *and* this later evidence step can raise `evidence_capture.TestTimedOut` — `build()` catches both identically (`lib/run_ticket.py:329-334`) and `settle()`'s `timed_out` branch (`lib/run_ticket.py:387-405`) always releases the claim and redispatches, which calls `run_ticket.py` fresh, which calls `execute_ticket()` again, which wipes the worktree and re-plans. That's the exact bug: a timeout *after* the code already passed throws away a passing build and re-plans from scratch. The existing test `test_a_timed_out_test_releases_the_claim_without_blaming_the_ticket` (`lib/tests/test_run_ticket.py:651`) only covers the *pre-passing* case (timeout inside `execute_ticket` itself) and must keep passing unchanged — that path is correct as-is, since no code has passed yet.

## Design

1. **Push the moment code passes, before evidence capture.** Add a small public wrapper in `mr_raiser.py` (e.g. `push_passing_code`) around the existing `_commit_and_push`. `build()` calls it right after `result["passing"]` is True, before attempting evidence capture, and writes a sidecar JSON into the worktree (`docs/design/<slug>-evidence.json`, next to the existing design-doc/task-list files, same slug helper) holding `{"final_comparison", "iterations"}` so a later evidence-only retry — which never calls `execute_ticket()` again — has what `raise_mr`'s PR body needs. That sidecar rides along in the same commit.

2. **Split the exception handling.** Wrap only the evidence-capture block (`lib/run_ticket.py:311-323`) in its own `try/except TestTimedOut`, separate from `execute_ticket()`'s. A timeout there produces a new outcome kind, `evidence_timed_out`, carrying the pushed branch name — never `timed_out` (so `execute_ticket`'s own timeout path, and its test, are untouched).

3. **`settle()`'s new `evidence_timed_out` branch:** counts trailing evidence-timeout markers on the issue (extend `_trailing_streaks` to a 3-tuple), and:
   - below a new cap (`MAX_EVIDENCE_RETRIES`): comments with a new marker (`EVIDENCE_TIMEOUT_MARKER`) plus the existing `retry_marker` backoff plus a new hidden `<!-- marvin:evidence-pending <branch> -->` marker, **releases the claim**, triggers redispatch. The branch and worktree are never touched by this path — nothing deletes them.
   - at/above the cap: opens the PR anyway (same code path as success, see 5) with an explicit "couldn't capture" note, never silently.

4. **Dispatch routing.** `ticket_pipeline.py`'s scan (near `_retry_not_before`, `lib/ticket_pipeline.py:710`) gets a matching `ticket_policy.evidence_pending(comments)` reader (same regex-over-comments idiom as `retry_not_before`). When present and not superseded by a later "passed"/person/handoff comment, `_build_wrapper_command` dispatches `run_ticket.py --evidence-only <repo>#<n> <branch>` instead of a plain rebuild — on whichever machine's scan picks it up next, which is already "a quiet moment, or the other Mac" since dispatch only happens when a machine has a free slot.

5. **New `run_ticket.evidence_only(issue_number, branch, repo)`:** checks the ticket is still **open** (else: no-op, no PR — satisfies "ticket closed meanwhile"); fetches and compares `origin/<base_branch>`'s tip against what the branch was built from — if main has moved, comments that the attempt is stale and falls back to a normal rebuild (clears the evidence-pending marker, lets the ticket re-enter the ordinary `ready-for-agent` pool) rather than reimplementing the merge gate's rebase-and-retest machinery here (see Decision `d-stale`); otherwise does a plain `git worktree add <path> <branch>` (no wipe — nothing needs preserving, unlike `_create_worktree`), reads the sidecar JSON, re-runs only `capture_test_results`/`capture_dev_evidence` (or `measurer.evidence()`), and on success calls `raise_mr` exactly as `build()` does. A further timeout reuses step 3's same counting/cap logic (factored into one shared helper so `build()` and `evidence_only()` don't duplicate it).

6. **"Couldn't capture" PR note.** Extend `mr_raiser._format_test_results` to recognize a `capture_failed` key on `test_results` and render `"⚠ Test evidence couldn't be captured: <why>. The merge gate's own run decides."` instead of the generic "Not available." — distinguishing "we tried and failed" from "not configured," and never printing a passed/failed/total count in that case.

7. **Protect the worktree in `cleanup_sweep`.** Add the same `ticket_policy.evidence_pending` read to `cleanup_sweep._default_list_worktrees`'s claimed-check path, and make `decide_worktree` return `("keep", "evidence capture is pending on this worktree")` whenever that marker is unresolved — independent of the `claimed:*` label, since the claim is deliberately released during this window. `disk_triggers.decide_merged` needs no change: it only acts once a branch has a *merged* PR, and an evidence-pending branch has no PR at all yet (confirmed by reading `lib/disk_triggers.py:244-260`) — a test proves this rather than assuming it.

8. **Purpose metric (AC3).** Add `_agent_builds_per_merged_pr` to `lib/purpose_metrics.py`, following `_replanned_tickets`'s exact pattern: numerator = count of `stage=="executing"/status=="started"/detail=="planning call"` events in the ticket-stages log over the window (`lib/sandbox_orchestration.py:319` is where that event is written — this fix directly shrinks this count); denominator = merged marvin PRs in the same window (`gh pr list --state merged`, same idiom as `disk_triggers._default_merged`). Register it in `MEASURES`. The baseline (2026-10-23→2026-10-30) must be computed from the Mac mini's historical `ticket-stages` log specifically, since that's where that window's data lives.

## Decisions

<!-- marvin:decisions -->
### d-cap: How many evidence-only retries before opening the PR with the "couldn't capture" note?
- [ ] A: Reuse `MAX_CONSECUTIVE_RETRIES` (5) — same cap the existing build-timeout path uses
- [ ] B: A smaller dedicated cap (2) — this failure mode is "machine busy," which should resolve fast or not at all
- [ ] C: 1 — any second evidence timeout opens the PR with the note immediately

### d-stale: Base branch moved on before the evidence-only retry runs
- [ ] A: Always fall back to a full rebuild (clear the evidence-pending marker, re-plan from current main) — simplest, no new rebase machinery
- [ ] B: Reuse the merge gate's own overlap-aware rebase-and-retest logic from `run_ticket.py` so a non-overlapping main move doesn't cost a rebuild

### d-breaker: Does an evidence-only timeout feed `failure_breaker` at all?
- [ ] A: No — this is "machine busy," not a sign the ticket or environment is broken (like `env_missing`, add to `BREAKER_EXEMPT`)
- [ ] B: Yes, under its own signature, separate from the existing build-timeout signature (so 3 machine-busy evidence timeouts still pause dispatch if the machine really is unhealthy)
<!-- /marvin:decisions -->

## Tests to write first

One per "How we'll try to break it" case, plus the misuse cases the section didn't name:

1. **Evidence times out twice, then succeeds: one build, one PR.** `build()` catches the evidence-step `TestTimedOut` (not `execute_ticket`'s own) → `evidence_timed_out` outcome, claim released, redispatch; `settle()` increments the new counter without touching the breaker/park path used for ordinary failures; `evidence_only()` called twice (still timing out) keeps releasing+redispatching; the third call succeeds and calls `raise_mr` exactly once — `execute_ticket`/the planner is never called again after the first build.
2. **Evidence never finishes: PR opens with the "couldn't capture" note and no test-count claims.** At the cap, the PR-opening path is called with `test_results={"capture_failed": "<why>", ...None fields}`; `_format_test_results` renders the explicit warning, never "Not available." and never a passed/failed number.
3. **The worktree is deleted by a disk sweep between attempts → falls back to a rebuild, with a stage note saying why.** `evidence_only()` is called with a branch whose local worktree no longer exists: it recreates one from the pushed branch via `git worktree add` (not `_create_worktree`'s wipe) and proceeds — no re-plan. Separately, prove `cleanup_sweep.decide_worktree` does NOT choose "backup"/"remove" while the evidence-pending marker is unresolved (new case, mirroring the existing `claimed=True` → `keep` tests in `lib/tests/test_cleanup_sweep.py`), and that `disk_triggers.decide_merged` already ignores a PR-less branch (a characterization test against the real function, not an assumption).
4. **The base branch moves on before the retry.** `evidence_only()` detects `origin/<base_branch>` has advanced past the branch's recorded base and takes whichever path d-stale resolves to (comments "stale, rebuilding" and clears the marker, or rebases+retests) — never silently runs evidence against a branch built on a now-stale base without saying so.
5. **A ticket closed by someone else meanwhile: no PR.** `evidence_only()` checks issue state first; on CLOSED, returns a no-PR outcome, posts no comment, opens nothing.
6. **`execute_ticket`'s own pre-passing `TestTimedOut` is unaffected** — the existing `test_a_timed_out_test_releases_the_claim_without_blaming_the_ticket` keeps passing unmodified; add a companion asserting it does **not** push anything and does **not** write the evidence-pending marker (proves the two paths stay genuinely separate).
7. **Bad/empty/malformed evidence-pending marker on the issue thread** (hand-typed, truncated, branch name with shell metacharacters) — `ticket_policy.evidence_pending` parses defensively like `retry_not_before` already does, and the branch name is never interpolated unsafely into a shell command (`_build_wrapper_command` already quotes/escapes; a test proves a malicious branch string can't break out of the dispatched command).
8. **Concurrent dispatch:** both Macs' scans see the same evidence-pending ticket in the same tick — the existing `_claim_is_ours_alone` race-back-off (`lib/ticket_pipeline.py:614-635`) already covers this for any claim; a test proves it still applies when the claim being raced for is an evidence-only one, not a fresh build.
9. **Wrong machine/no toolchain:** the machine that picks up the evidence-only retry lacks a required tool (`project_profile.EnvMissing`) — same `env_missing` handling as today, claim released, no strike, no park.
10. **Stale claim on an evidence-pending ticket:** `cleanup_sweep.sweep_stale_claims` still releases a claim that outlives its run even mid-evidence-retry (no special exemption needed — the worktree protection in test 3 is independent of claim state).
11. **A person comments on the ticket while evidence is pending** — `ticket_policy.evidence_pending` (like `automated_comment`/`retry_not_before`) must treat a human reply as ending the automated state, not as noise to skip past.
12. **Purpose metric correctness:** `_agent_builds_per_merged_pr` counts exactly the "planning call" events (not "planning reused from round 1") in the window, and divides by merged-PR count in the same window; division-by-zero (no PRs merged in the window) is handled explicitly, not a crash.

## Task List

1. Add `mr_raiser.push_passing_code(worktree_path, ticket_ref)` as a thin public wrapper around `_commit_and_push`; export the evidence-sidecar writer (`docs/design/<slug>-evidence.json`) alongside the existing `_design_doc_path`/`_task_list_path` helpers in `sandbox_orchestration.py`.
2. In `run_ticket.build()`, call the push + sidecar write immediately after `result["passing"]` is True, before evidence capture; wrap the evidence-capture block in its own `try/except TestTimedOut` producing the new `evidence_timed_out` outcome (branch, worktree_path, reason) — leave `execute_ticket()`'s own exception handling untouched.
3. Extend `run_ticket._trailing_streaks` to a 3-tuple (failures, build-timeouts, evidence-timeouts) and add `EVIDENCE_TIMEOUT_MARKER`, `MAX_EVIDENCE_RETRIES` (per `d-cap`).
4. Add the `settle()` branch for `evidence_timed_out`: below cap → comment + `retry_marker` + new `marvin:evidence-pending` hidden marker + release claim + redispatch; at/above cap → open the PR anyway via the shared "open with whatever evidence we have" path.
5. Factor the "open the PR, formatting whatever test_results/dev_evidence exist (possibly a capture-failure note)" logic into one function shared by `build()`'s success path, `settle()`'s cap-exceeded path, and `evidence_only()`'s own success/cap-exceeded paths.
6. Extend `mr_raiser._format_test_results` to render the explicit "couldn't capture" note from a `capture_failed` key.
7. Add `ticket_policy.evidence_pending(comments, now)` (mirrors `retry_not_before`), ending on a human comment like `automated_comment` already does.
8. Add `run_ticket.evidence_only(issue_number, branch, repo)`: ticket-open check, base-branch staleness check (per `d-stale`), plain `git worktree add` from the pushed branch, sidecar read, evidence capture, success/timeout handling via the shared functions from steps 3-5.
9. Wire dispatch routing in `ticket_pipeline.py`: read `ticket_policy.evidence_pending` alongside the existing `_retry_not_before` check per ready ticket; extend `_build_wrapper_command` to emit the `--evidence-only` form.
10. Add the `evidence_pending` signal to `cleanup_sweep._default_list_worktrees`/`decide_worktree` so a pending evidence retry is always kept; add the characterization test proving `disk_triggers.decide_merged` already ignores PR-less branches.
11. Resolve `d-breaker` and wire `evidence_timed_out` into (or explicitly out of) `failure_breaker` accordingly.
12. Add `purpose_metrics._agent_builds_per_merged_pr` and register it in `MEASURES`; compute and record the 2026-10-23→2026-10-30 baseline from the Mac mini's `ticket-stages` log (run on mac-mini-1), filling in the ticket's own Purpose metric section per the existing format `purpose_metrics.parse` expects.
13. Write all tests from the list above, covering `run_ticket.py`, `mr_raiser.py`, `ticket_policy.py`, `ticket_pipeline.py`, `cleanup_sweep.py`, `disk_triggers.py` (characterization only), and `purpose_metrics.py`.
14. Update `docs/life-of-a-ticket.md`'s "Verify" step (7) and the red-list/loop tables if this changes any documented behavior (new loop: "Evidence retry").