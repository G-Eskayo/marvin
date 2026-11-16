## North-star fit

**Reuses:** `lib/ticket_queue.py:build_queue` already reuses `ticket_pipeline._order_key` and (via the injected `ready` callback) `ticket_pipeline._unclaimed_ready_tickets` — ADR 0053's "one source of truth" so the strip can't drift from the scanner. The dashboard already solved half of this ticket once, client-side: `dashboard/src/lib/next_step.js:182-187` dedupes the same `queue:list` rows by `(repo, number)`, keeping the first position, with the comment *"The queue can list a ticket twice (a repo read twice)"*. I'm porting that exact intent into the Python source itself, which is what the ticket asks for ("the queue itself should be right, because the pipeline and the estimator read it too") — one fix instead of every consumer re-deriving it. I'm leaving the JS dedup in place rather than ripping it out: once the root is fixed it's redundant but harmless, and removing unrelated code isn't this ticket's job.

**Simplest sufficient approach:** For "each ticket appears once," the duplication's root cause is concrete, not hypothetical: `G-Eskayo/marvin` is `HOME_REPO` in `lib/project_profile.py:31`, and `project_profile.profile_problems` (line 273) explicitly special-cases a profile whose `repo == HOME_REPO`, so marvin legitimately has its own profile file alongside other projects. `ticket_queue.current_queue()` builds `repos = [tp.REPO, *pp.dispatchable_repos()]` with no dedup — if marvin's own profile has `dispatch: "on"` (it must, since marvin's own tickets dispatch), marvin is read twice, and every one of its ready tickets is scored, sorted and emitted twice, landing adjacent (exactly "#821 at positions 1 and 2"). The fix is two one-line changes in the same function family, no new abstraction: dedup the `repos` list before fetching, and dedup `pairs` by `(repo, number)` after sorting (keeping the first — same "first wins" rule the JS already validated).

For "a ticket with an open PR that closes it isn't ready," I read `lib/ticket_pipeline.py:132-183`, `lib/ticket_evidence.py`, and CONTEXT.md line 1492 closely. This is **already built and already tested** (`test_unclaimed_ready_skips_tickets_that_already_have_work`): `_unclaimed_ready_tickets` runs every ready ticket through `ticket_evidence.verdict()`, and an open PR whose body contains `Closes #N` (which every PR must have — `bin/gh`'s `pr_ticket_check.py` gate refuses a PR body that names no ticket) is always a textual `#N` substring, so `_mentions` always catches it. The one documented exception — a `needs-reengagement` ticket is re-dispatched despite its own open PR/branch — is a closed, Gil-decided design choice (CONTEXT.md line 1575, "Sent-back loop"), not a defect, and this ticket gives no reason to revisit it. So: **no production change for this criterion** — I'll write the acceptance tests against the existing code to prove and lock in what's already correct, per "if existing code already satisfies this ticket, say so and act on that."

**Tokens/resources:** the `repos` dedup also removes a wasted `gh issue list`/`gh pr list` round-trip per scan for marvin (ADR 0052 measured ~1,235 GitHub calls/hour against a 5,000/hour budget) — direct north-star-1 saving, not just a side effect. Criterion 2 needing zero code costs nothing beyond the tests that prove it.

**More capable, not more passive:** the owner gets a queue (and, later, the estimator in #948) that tells the truth about what's next and what's already in flight, instead of silently working around a wrong queue the way PR #1030 had to.

## Decisions

None. The duplicate-repo cause is confirmed by reading `project_profile.py` + CONTEXT.md, not guessed; the open-PR criterion is confirmed already-correct and documented as a closed decision. Nothing here needs the owner to choose between options.

## Tests to write first

In `lib/tests/test_ticket_queue.py` (extends the existing `issue()`/`build()` fixtures):
1. A repo read twice (`repos=["o/a","o/a"]`, same `ready()` ticket both times) → ticket appears exactly once, at position 1. (Ticket's "A ticket on two boards".)
2. The same ticket **number** in two different repos (`repos=["o/a","o/b"]`, each returns ticket #1) → both rows survive, not collapsed into one — guards against a dedup key of `number` alone instead of `(repo, number)`.
3. A duplicated repo mixed with a real second ticket (`repos=["o/a","o/a","o/b"]`) → exactly 2 rows with positions `[1, 2]`, no gap and no phantom 3rd row.
4. Existing tests (`test_orders_across_projects_by_the_scanners_order_key`, `test_a_project_that_cannot_be_read_does_not_hide_the_others`, etc.) must keep passing unmodified — the dedup must not change ordering or the "unreadable repo doesn't hide others" behavior.

In `lib/tests/test_ticket_pipeline.py` (extends the existing `_stub_issues`/`PR_FACTS` fixtures):
5. One open PR whose body is `"Closes #7\nCloses #8"` plus a control ticket #9, all three `ready-for-agent` → only #9 stays ready. (Ticket's "A PR that closes two tickets.")
6. Same ticket, two-phase: first with the closing PR present → ticket excluded; then with `_evidence_facts` returning empty `prs` (the PR closed without merging) → the same ticket is ready again on the very next read, proving nothing caches the old exclusion. (Ticket's "A PR closed without merging.")
7. Re-run (not rewrite) `test_unclaimed_ready_still_dispatches_when_evidence_unreadable` and `test_a_sent_back_ticket_is_redispatched_even_though_its_old_pr_is_open` as regression gates — my change must not touch this code path at all.

Misuse cases the ticket's list didn't name, added here: different-repo/same-number collision (#2 above, a person's mistake creating two profiles for one repo would otherwise merge unrelated tickets); no-gap position numbering at scale (#3); and the stale-state/no-caching proof (#6) — confirming a closed-then-reopened PR doesn't leave the ticket permanently "in-flight".

## Task List

1. `lib/tests/test_ticket_queue.py`: add the three new dedup tests (items 1-3 above) against the current (unfixed) `build_queue` — they should fail, proving the bug.
2. `lib/tests/test_ticket_pipeline.py`: add the two new evidence tests (items 5-6 above) against current code — they should already pass, proving criterion 2 needs no fix.
3. `lib/ticket_queue.py`: in `current_queue()`, dedup `repos` (`list(dict.fromkeys([tp.REPO, *pp.dispatchable_repos()]))`) before fetching, so a repo registered twice (e.g. marvin's own profile alongside the hardcoded `tp.REPO`) is read once.
4. `lib/ticket_queue.py`: in `build_queue()`, after `pairs.sort(key=...)`, drop later duplicates keyed by `(repo, t["number"])` before building the position-numbered output list, keeping each ticket's first (best-sorted) occurrence.
5. Run the full `lib/tests/test_ticket_queue.py` and `lib/tests/test_ticket_pipeline.py` suites; confirm the new tests from steps 1-2 now pass and nothing else regresses.
6. Update `lib/ticket_queue.py`'s module docstring if needed to note the dedup guarantee (one line, only if the existing docstring would otherwise read as inaccurate).