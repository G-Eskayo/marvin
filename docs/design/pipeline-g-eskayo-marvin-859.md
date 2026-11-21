## North-star fit

**Reuses:** the loop test already exists and is already the right shape — `lib/tests/test_work_loop_e2e.py` (I2, marvin#742) drives the real `bin/gh` gate against a fake "real gh" in a temp HOME, and its own docstring says "each rule adds its own section." I1's pure logic is unit-tested in `lib/tests/test_pr_images.py` (`verdict()`, `parse_pr_call()`) but never driven through `bin/gh`'s `ui_evidence_refusal()` end-to-end. I3's logic is thoroughly unit-tested in `lib/tests/test_owner_decisions.py` (`FakeGitHub`, `sync()`, `waiting()`, `request()`) but never exercised through the same sandbox as I1/I2, and never assembled into one ticket-to-merge narrative. The "never touches real HOME/GitHub, refuses to start otherwise" requirement is **already** provided for every test file by the root `conftest.py` (global `HOME` swap to a temp mirror before any test imports, a global `WriteGuard`, and a refusing `gh` stub first on `PATH`) plus pytest's own `tmp_path`. "Runs in the merge gate's test suite" is already automatic: `lib/affected_tests.py` always includes "every changed test file," and main-health runs the full suite regardless. So this ticket adds **no new infrastructure for isolation or CI wiring** — only new test code, growing the one file ADR 0080 already designated, plus two small test-only helpers (a routable fake "real gh" for I1's GitHub answers, and a `run=` bridge so `owner_decisions.py`'s calls go through the same sandboxed `PATH`/`HOME` as the `bin/gh` calls).

**Simplest sufficient approach:** no production code changes are needed — `ui_evidence_refusal()`, `pr_images.verdict()`, and `owner_decisions.sync/waiting/request` already take injectable `ask`/`run` callables built for exactly this. The gap is pure test coverage: I1 and I3 were proven in isolation but never driven through the real choke points together, and the ticket's own failure shapes (#724, #678-style reordering, mid-loop GitHub failure) were never asserted at this level.

**Resource cost:** this spends test time (new subprocess-driven tests, each with the file's existing 60s timeouts) to stop the exact recurring failure shape ADR 0080 names — a rule that holds in one unit test but is silently skipped by another caller. It adds no runtime code, no new daemon, no new file beyond test code, so there is no ongoing resource cost, only a slightly longer test run.

**Phone-OS direction:** none directly — this is reliability plumbing (north star 3's precondition: "nothing may break silently"). It makes the *next* two tickets in ADR 0080's order (I4's `next_step()`, I5's liveness checker) safe to build on, because the loop test will catch a regression in I1–I3 while they're built.

**More capable, not more passive:** this is infrastructure that lets the owner trust silence (a green loop test) instead of re-discovering drops by hand (as happened with #724 for six days). It doesn't automate anything the owner currently does by hand.

## What's already built (verified by reading the code, not assumed)

| Piece | Where | State |
|---|---|---|
| I1's pure logic (`verdict`, `image_urls`, `link_problem`, `pinned_shas`, `with_shots_section`) | `lib/pr_images.py`, tested in `lib/tests/test_pr_images.py` | Done, unit-level only |
| I1's `bin/gh` choke point (`ui_evidence_refusal`) | `bin/gh:267-302` | Built, **never driven end-to-end against a fake GitHub** |
| I2's `bin/gh` choke point + e2e coverage | `lib/decisions_check.py`, `lib/tests/test_work_loop_e2e.py` | **Fully done** (marvin#742/PR #744) |
| I3's trigger (`waiting`, `sync`, `request`, `pr_built_status`) | `lib/owner_decisions.py`, unit-tested in `lib/tests/test_owner_decisions.py` with its own `FakeGitHub` | Done, unit-level only, never run through the `bin/gh` sandbox or the e2e walk |
| I3's "earlier unapproved rounds stay viewable as variations" | `docs/design/737-review-variations.md` | **Status: proposed, nothing built.** Not in scope — ticket's own "How we'll try to break it" list doesn't require it either |
| Real-HOME/real-GitHub protection for every test | root `conftest.py` (`real_home_guard.make_test_home`, `install_write_guard`, refusing `gh` stub) | Already universal, nothing to add |
| Merge-gate test selection | `lib/affected_tests.py` | Already includes any changed test file; no wiring needed |
| I4 (`next_step()`), I5 (liveness checker), #678's dashboard fix, #231's merge queue UI | not built yet | Out of scope — ADR 0080's own order puts them after this ticket |

## Decisions

None — the open design points (whether to grow the existing file vs. start a new one; how to represent the not-yet-built "ship step") are both already settled by ADR 0080's own text ("each rule adds its own section" to `test_work_loop_e2e.py`; "I4: `next_step()`... ship step" comes *after* "the loop test, first for I1–I3" in the Order section) and by the sequence the owner already approved. No prose question needed.

## Tests to write first (one file, `lib/tests/test_work_loop_e2e.py`, extended — no new file)

New test-only helpers (no production code touched):
- `_route_gh(tmp_path, realbin, routes)`: writes a small JSON file of canned `{argv-prefix: json-response}` answers and rewrites the fixture's fake "real gh" script to serve them (default `{}` as today), so I1's `repo view`, `api repos/{repo}`, `api repos/{repo}/compare/...`, and `pr view --json files,body,headRefOid` calls can be scripted per test.
- `_od_run(tmp_path, realbin)`: a `run=` callable for `owner_decisions.py`'s functions that reuses the *same* `PATH`/`HOME` env as `_gh()`, so I3's reader goes through the identical sandbox as the `bin/gh` writer, in the same test.

Tests (each maps to a line in the ticket's "How we'll try to break it," plus the misuse cases it didn't spell out):

1. `test_i1_a_ui_change_with_no_pinned_images_is_refused_through_bin_gh` — `pr create` with a UI file in the fake `compare` response and no image in the body → `NO_UI_EVIDENCE`, nothing reaches GitHub.
2. `test_i1_a_stale_pinned_image_is_refused_through_bin_gh` — an image pinned to an earlier commit, `compare(pinned_sha, head)` shows a later UI file change → `STALE_UI_EVIDENCE`, blocked.
3. `test_i1_current_pinned_images_reach_github` — a current, correctly pinned image → the call reaches the fake GitHub unchanged (the good path, symmetric with the existing I2 "good" tests).
4. `test_i1_a_fix_pushed_after_a_refusal_passes_the_same_check_again` — call 1 (stale/missing images) refused; call 2 with corrected content (simulating the pushed fix) succeeds — the choke point has no memory that would strand it (the #678 shape, tested at the level this ticket can reach without the unbuilt dashboard fix).
5. `test_i3_a_push_with_no_reply_leaves_the_pr_waiting` — via `_od_run`: a commit lands after the owner's Decisions comment with no `marvin:decisions-addressed` reply → `waiting()` still lists it, `sync()` files the follow-up.
6. `test_i3_a_reply_with_the_addressed_marker_closes_the_follow_up` — the reply is posted *through `bin/gh`* (proving I2 doesn't block a legitimate reply) and the next GitHub snapshot carries it → `sync()` closes the follow-up, `waiting()` is empty.
7. `test_i3_approve_before_decisions_answered_requests_nothing` — "steps out of order": `request()` on a PR with no Decisions comment at all returns "nothing to request," writes nothing.
8. `test_i3_a_silent_no_op_scan_never_marks_an_overdue_pr_as_addressed` — the #724 shape: patch the write step to report success while writing nothing; assert `waiting()` still lists the PR — a job that lies about doing its job still leaves the item visibly undone, never falsely "handled."
9. `test_i3_github_failing_mid_scan_leaves_the_item_stuck_not_dropped` — the fake GitHub returns a rate-limit/5xx failure mid-scan: `sync()` returns `ok: False`, an existing open follow-up stays open, nothing new is filed or closed, and `fetch()`/`waiting()` return `None` rather than a false empty list.
10. `test_the_loop_walks_a_ticket_from_idea_to_merged_through_i1_i2_i3` — the one end-to-end narrative: `issue create` (ticket) → `pr create` (mock-up PR, pinned current images + a machine-readable Decisions block) both reach GitHub through `bin/gh` → the owner's Decisions comment is simulated in the next snapshot → a build commit lands with no reply (I3 sees it waiting, files a follow-up) → the reply is posted through `bin/gh` (I2-checked) → I3's next snapshot shows it addressed → `request()` (approve) is a no-op since it's already addressed → `pr merge` succeeds through `bin/gh` (I1/I2 re-checked on the merge call too) and is recorded as the stand-in "ship" step (GitHub's own close-on-merge via the PR's `Closes #N`), since I4's real ship step doesn't exist yet.
11. `test_the_suite_never_touches_the_real_home_or_github` — asserts this file's own `tmp_path`-rooted `HOME` resolves outside `real_home_guard.real_home()`, and that `find_real_gh` in this sandbox's `PATH` can only resolve to the fixture's fake binary, never a real one — a concrete, file-local proof on top of the root `conftest.py`'s universal guarantee.

## Task List

1. Add `_route_gh()` and `_od_run()` helpers to `lib/tests/test_work_loop_e2e.py`, reusing the existing `github`/`_gh`/`_reached`/`_gate_log` fixtures without modifying them (the current I2 tests must keep passing unchanged).
2. Write the I1 section: tests 1–4 above, against `bin/gh`'s real `ui_evidence_refusal()`.
3. Write the I3 section: tests 5–9 above, against the real `owner_decisions.py`, routed through the same sandbox env as I1/I2.
4. Write the single end-to-end walk test (10).
5. Write the sandbox-guarantee test (11).
6. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_work_loop_e2e.py -v` locally in this worktree and confirm all pass on today's main, including the existing I2 tests.
7. Confirm each new test fails for the right reason when its guard is disabled (e.g. temporarily stub `pr_images.verdict` to `lambda *a, **k: []`, or `owner_decisions._file` to a no-op, re-run, observe the specific new test fail, then restore) — this is verification of the tests themselves, not a code change to keep.
8. Open the PR noting it reuses `bin/gh`, `lib/pr_images.py`, and `lib/owner_decisions.py` as-is (no production diff), names `marvin#859` and its parent `marvin#737`/ADR 0080, and states plainly that I4–I6 and the dashboard-side fixes (#678, #231, #729) are the next tickets in the ADR's own order, not this one's job.