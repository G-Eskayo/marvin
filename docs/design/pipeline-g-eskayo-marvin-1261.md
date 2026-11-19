## North-star fit

**Reuses:** `lib/owner_decisions.py` `request()` (marvin#231's existing "ask for the follow-up now, no grace" entrypoint) and its `_file`/`_dedupe`/`pr_status` machinery; `dashboard/webhook-server/decisions_gate.js`'s existing single-purpose-assert pattern (`assertDecisions`) and its home as "the merge-server check" file (docs/agents/decisions-format.md); `merge.js`'s existing refusal/`MergeFailure` family and `DECISIONS_UNCHECKED`'s fail-closed wording; `merge_order.js`'s `HOLD_UNTIL` map. No new loop, no new cache, no new abstraction — the two gaps are closed by (a) one more fresh, synchronous check at the one point in `mergePrUnqueued` that actually calls `gh pr merge`, and (b) teaching the *existing* `request`/`sync` functions to fall back to a single-PR read when the broad open-PR search can't see a merged PR, instead of assuming "not open" means "safe to close."

**Simplest sufficient approach:** rather than widening the hourly scan's GraphQL query to also trawl merged PRs (expensive, unbounded, still polling), the brand-new "owner answers *after* merge" case is caught at its true source — the Submit-decisions action itself, which already knows the instant an answer is recorded and already knows (from the issue it just re-read) whether that PR is still open. That's trigger-based, not polling, matching the module's own stated design philosophy and `feedback-trigger-based-not-polling`.

**Token/resource cost:** one extra `owner_decisions.py request` invocation (one GraphQL call, one repo) at the one still-open decision point in `mergePrUnqueued`, right before every real merge — bounded, necessary for correctness. The merged-PR fallback fetch only runs for the rare case a follow-up's PR has left the open set, or a Submit lands on an already-closed PR — not on every scan.

**Phone-OS direction:** neutral — this is pipeline-internal correctness, not user-facing surface.

**More capable or more passive:** more capable — Gil can answer a Decision whenever he actually notices it, on his own schedule, and trust MARVIN to act on it, instead of having to remember to chase it into another PR by hand (exactly what happened with #1248 → #1260).

## Decisions

A genuine open design tradeoff, not something to guess silently:

<!-- marvin:decisions -->
### backstop: Hourly scan backstop for merged-PR Decisions, or submit-time trigger alone?
- [ ] A: Submit-time trigger only (this plan's default). Cheapest; fails if the Submit-time call itself never runs (crash, network blip) with no later catch — a single point of failure for that one case.
- [ ] B: Also widen the hourly scan to re-check PRs merged within a bounded lookback window (e.g. 7 days, matching the existing parked-choice review window, marvin#1222) as a backstop, at the cost of a wider GraphQL read (full comments/commits) on every recently-merged PR, every scan, for every registered repo.

## Tests (written first)

**decisions_gate.js — `assertDecisionsBuilt` (new, in `dashboard/test/decisions.test.js`):**
1. `owner_decisions.py request` prints `filed ...` → rejects `DECISIONS_UNBUILT`.
2. prints `already filed` → rejects `DECISIONS_UNBUILT` (closes AC1: "Approve, then answer, then a merge that runs before the cache refresh").
3. prints `nothing to request: no owner Decisions on this PR` → resolves.
4. prints `nothing to request: already addressed (...)` → resolves.
5. `exec` throws → rejects `DECISIONS_UNCHECKED` (fail closed: "GitHub unreadable at merge time: hold, never merge on a guess").
6. prints `skipped: could not read GitHub` (exit 0, unreadable) → rejects `DECISIONS_UNCHECKED` too.
7. empty/garbage stdout → fails closed, never silently treated as "nothing to request".
8. an unparseable PR URL → doesn't crash (mirrors the other asserts' tolerance for this one case, which `mergePrUnqueued` already guards earlier anyway).

**merge.js integration (`dashboard/test/merge.test.js`):**
9. `decisionsBuilt` is called once, after the gate/retest stage finishes and before `gh pr merge` runs (assert call order against the fake exec's recorded calls).
10. When it throws `DECISIONS_UNBUILT`, `gh pr merge` is **never** called — the literal regression test for the #1248 incident.
11. The 4 files that `vi.mock('../webhook-server/decisions_gate.js', ...)` (merge.test.js, merge_memory_guard.test.js, gate_flaky_rerun.test.js, merge_gate_progress.test.js) still pass once the mock also stubs `assertDecisionsBuilt`.
36. A stacked PR's own after-steps merge (`repoJobsDone`) still runs the same `mergePrUnqueued` path, so its own unaddressed Decisions are still caught — not special-cased away (ticket's own break-it list: "a stacked PR merged by its base's after-steps").

**owner_decisions.py `request()` fallback (`lib/tests/test_owner_decisions.py`):**
12. Merged PR (absent from `is:open`), unaddressed Decisions comment, no existing follow-up → files one (AC2).
13. Same, but a follow-up for that exact comment id is already open → `"already filed"`, nothing new filed.
14. Same, but a reply with `ADDRESSED_MARKER` already followed it → `"nothing to request: already addressed (reply)"`.
15. Same, but the body now reads as "as built" → `"...already addressed (as-built)"`.
16. Merged PR with no Decisions comment at all → `"nothing to request: no owner Decisions on this PR"`, no crash.
17. The fallback single-PR fetch itself fails → `"skipped: could not read GitHub"`, nothing filed on a guess.
18. Fallback fetch returns garbage/unparseable JSON → same fail-closed result.
19. Two Macs call `request()` concurrently on the same freshly-merged PR → existing `_dedupe` still collapses to exactly one open follow-up.

**owner_decisions.py `sync()` no longer wrongly closes:**
20. **Rewrite** `test_follow_up_closes_when_the_pr_closes_but_not_when_the_list_was_cut_short`'s second half: a PR leaves the open set while its Decisions comment is still unaddressed → the follow-up **stays open** (AC2's second half — this currently-passing assertion encodes the bug and must flip).
21. PR leaves the open set and a fresh fallback read shows it's now addressed (reply) → the follow-up closes, same "addressed" wording (AC3).
22. Same, addressed via "as-built" → closes too.
23. PR leaves the open set and the fallback read for that one PR fails → left open, nothing closed on a guess.
24. The existing truncated-open-PR-list safeguard (`data["complete"] is False` ⇒ close nothing) still passes unmodified.
25. A follow-up references a PR number `gh pr view` now 404s on → treated like "could not read it": left open, no crash.

**decisions_submit.js — the submit-time trigger (`dashboard/test/decisions_submit.test.js`):**
26. Submitting answers on a PR with `issue.state === 'closed'` → after the record comment, `owner_decisions.py request` is invoked for that repo/number.
27. Submitting on an **open** PR → the call is **not** made (unchanged: the merge gate / hourly scan still own that case).
28. Submitting on a plain ticket (`issue.pull_request` absent) → never called, regardless of state.
29. The request call itself fails/rejects → `submitDecisions`'s own result (comment/label outcome) is unaffected, same swallow-and-log pattern as the existing `comment`/`move` promises.
30. `background: true` path: covered by the same `recorded` promise already returned; no new unhandled rejection.

**Misuse beyond the ticket's own list:**
31. A comment body near GitHub's size limit on a merged PR → fallback fetch/parse still works (`comments(last: 30)`, same bound as the main query).
32. `owner_decisions.py request --repo R --pr abc` (non-numeric) → usage error (exit 2), not a crash.
33. Bad `gh` auth on the single-PR fallback call → `"skipped: could not read GitHub"`, same contract as the broad fetch's own auth failures.
34. A follow-up's marker names a comment id that's no longer the PR's *latest* Decisions comment (owner posted a newer one after merge) → the fallback recomputes against the latest comment, never suppressed by the stale marker.
35. The owner double-clicks Submit on the same merged PR → absorbed by the existing dedupe, driven through the JS path this time.

## Task List

1. `lib/owner_decisions.py`: add a single-PR GraphQL fallback (`_fetch_one(repo, number, run)`), same node shape as the main query (`databaseId` on comments, required for `followup_marker` compatibility), no commits needed.
2. `lib/owner_decisions.py`: `request()` — when the PR isn't in the open-PR search, fall back to `_fetch_one` + `pr_status(..., grace=0.0)` before deciding "nothing to request" / "already filed" / file.
3. `lib/owner_decisions.py`: `sync()` — replace the "not in `open_prs` ⇒ close as 'no longer open'" branch with: fetch that one PR via `_fetch_one`, recompute its status, close only if truly addressed (reply/as-built), otherwise leave the follow-up open; a failed fallback read also leaves it open.
4. `lib/tests/test_owner_decisions.py`: add tests 12–19, 21–23, 25, 31–35; rewrite test 20's assertion; confirm test 24 still passes untouched.
5. `dashboard/webhook-server/decisions_gate.js`: add `assertDecisionsBuilt(prUrl, exec)` — shells to `owner_decisions.py request --repo R --pr N` (own `VENV_PYTHON`/script-path constants, mirroring `merge_facts.js`), interprets `filed`/`already filed` as `DECISIONS_UNBUILT` (action `reengage`), `skipped:*`/a thrown error as `DECISIONS_UNCHECKED`, anything else as pass. PR-number parsed with a local one-line regex (not imported from `merge.js`, to avoid a circular import).
6. `dashboard/webhook-server/merge.js`: import `assertDecisionsBuilt`, add `decisionsBuilt = assertDecisionsBuilt` to `mergePrUnqueued`'s deps, call `await decisionsBuilt(prUrl, exec)` immediately before `stage('merging', 'started', '')` (~line 1016) — after the gate/retest finishes, as late as possible before the real `gh pr merge`.
7. `dashboard/webhook-server/merge_order.js`: add `DECISIONS_UNBUILT: 'later'` to `HOLD_UNTIL`, matching `DECISIONS_UNCHECKED`'s existing treatment.
8. Update the 4 `vi.mock('../webhook-server/decisions_gate.js', ...)` call sites to also stub `assertDecisionsBuilt`.
9. `dashboard/test/decisions.test.js`: add the `assertDecisionsBuilt` describe block (tests 1–8); `dashboard/test/merge.test.js`: add tests 9, 10, 36.
10. `dashboard/electron/main/decisions_submit.js`: in `recordAnswers`, when `issue.pull_request && issue.state !== 'open'`, fire the same `owner_decisions.py request` call (own local path constants) as a third parallel, never-rejecting promise alongside `comment`/`move`.
11. `dashboard/test/decisions_submit.test.js`: add tests 26–30.
12. Resolve the Decisions block above (backstop or not) before closing; if B is chosen, add the bounded-lookback query and its own tests.
13. Update `docs/agents/decisions-format.md`'s "After the owner answers: it is MARVIN's move" section and `CONTEXT.md`'s "Owner decisions waiting on MARVIN" entry to describe the merge-time recheck and the merged-PR fallback.