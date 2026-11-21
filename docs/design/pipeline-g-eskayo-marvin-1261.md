Clean worktree, nothing to build on from prior failed attempts. Here is the implementation plan.

## North-star fit

**Reuses:** the existing per-merge gate-assertion pattern in `dashboard/webhook-server/merge.js::mergePrUnqueued` — `assertDecisions` (`decisions_gate.js`), `assertNotSentBack`, `readyIfDraft` all run as cheap, injectable, fail-closed checks *before* the heavy rebase+retest gate. The fix adds one more step of that same shape rather than a new loop, cache, or watcher — satisfying the ticket's own "What to build (reuse, don't add a loop)" header. On the Python side it reuses `owner_decisions.py`'s existing `fetch()`/`statuses()`/`pr_status()` (the same functions `request()` already calls), factored into one shared helper so no logic is duplicated.

**Why simplest sufficient:** the bug is a race between a ~20 s cache-refresh window and a merge; the fix is a single fresh, synchronous read at the one choke point every merge already passes through (`mergePrUnqueued`), not a shorter poll interval or a second cache. Considered and rejected: forcing `index.js`'s shared `unbuiltCache.refresh()` from inside `merge.js` — rejected because `merge.js` is deliberately isolated from `index.js` singletons ("unit-testable without spinning up a real server," merge.js:718) and every existing gate step already does its own independent fresh `gh`/script read rather than reach into one.

**Cost:** one extra `gh api graphql` call per merge attempt (same order of magnitude and the same precedent as the existing `assertDecisions`/`assertNotSentBack` per-merge reads) — it does not add a timer, a second cache, or a new trigger. The `sync()` fix adds at most one extra GraphQL call per currently-open follow-up whose PR just left the open list (small, bounded, no caller already absorbs a bigger "2 points" cost quoted in the module's own docstring).

**More capable, not more passive:** closes a gap where an owner's answer could silently vanish with nobody noticing (exactly the north star "nothing breaks silently"); Gil doesn't have to remember to check that a late Decisions answer landed — MARVIN now guarantees it either blocks the merge or gets a ticket.

**Machine:** no preference — this is webhook-server (Node) + `lib` (Python) code, run wherever the merge server/hourly scan already run.

---

## Where it's dropped — confirmed by reading the code

1. `merge_order.js::ownReason` only sees `decisionsUnbuilt` through the `unbuilt` Set passed in from `index.js`'s `unbuiltCache` (refreshed on triggers, not synchronously before a merge). `merge.js::mergePrUnqueued` never re-checks the owner-Decisions **comment** itself — it only checks the PR-body Decisions block, via `assertDecisions`/`decisions_gate.js`. These are two different mechanisms (PR body checkboxes vs. the dashboard's "Decisions from the owner" *comment*, tracked by `lib/owner_decisions.py`) and only the first is gated live at merge time.
2. `owner_decisions.py::fetch()` queries `is:pr is:open` only, so `sync()`'s `by_pr` never has an entry for a merged/closed PR; `sync()`'s `elif (repo, pr) not in open_prs and data["complete"]: why = "PR #{pr} is no longer open."` closes the follow-up purely because the PR left the open list — regardless of whether the answer was ever addressed. Confirmed this closes an unaddressed follow-up on every merge, not just ones that were actually handled.

## What I'm building

**A. Merge-time fresh check (closes gap 1 — AC1)**

- `lib/owner_decisions.py`: extract the fetch+find logic already inside `request()` into a private `_fresh_status(repo, number, now, run)` (returns `(data, s)`, unchanged behavior for `request()` — same tested strings). Add `pr_built_status(repo, number, now=None, run=subprocess.run) -> dict` reusing it, returning `{"ok": bool, "built": bool, "reason": str}` (`ok=False` only when GitHub is unreadable). Add a `status --repo R --pr N [--json]` CLI subcommand (read-only — no filing side effect, unlike `request`).
- New `dashboard/webhook-server/owner_decisions_gate.js`, mirroring `decisions_gate.js`: `assertOwnerDecisionsBuilt(prUrl, exec)` shells `owner_decisions.py status --repo R --pr N --json` fresh every call and throws `MergeFailure` with code `OWNER_DECISIONS_UNCHECKED` (GitHub unreadable / bad response — "never merge on a guess") or `OWNER_DECISIONS_UNBUILT` (confirmed unaddressed) when not built; resolves silently otherwise.
- `merge.js::mergePrUnqueued`: add `ownerDecisionsBuilt = assertOwnerDecisionsBuilt` to `deps`, call `await ownerDecisionsBuilt(prUrl, exec)` right after the existing `await decisions(prUrl, exec)` line (before any gate/rebase work — cheap-first, same place `assertDecisions` already sits).
- `merge_order.js::HOLD_UNTIL`: add `OWNER_DECISIONS_UNCHECKED: 'later'` and `OWNER_DECISIONS_UNBUILT: 'later'` (same "retry later, no fixed key, no bounded tries" treatment as `DECISIONS_UNCHECKED`/`GATE_INFRA` — an unbuilt answer may legitimately take hours, so it must not count toward `TEMPORARY_TRIES` and leave the queue).

A stacked PR merged by its base's after-steps needs no special-casing: after-steps only *rebase* a stacked PR onto the new base (`merge.js` comment "move stacked PRs onto the base"), they don't merge it — its own eventual merge still goes through this same `mergePrUnqueued` gate.

**B. `sync()` never drops a merged PR's unaddressed answer (closes gap 2 — AC2/AC3)**

- `lib/owner_decisions.py`: add a single-PR GraphQL query (`repository(owner,name){ pullRequest(number){...} }`, same PullRequest field set `_QUERY` already selects) and `fetch_pr(repo, number, run) -> dict | None`, returning the identical per-PR dict shape `fetch()` builds, so `pr_status()` works unchanged on it.
- `sync()`: when an open follow-up's PR is not in `open_prs` **and** the page list was complete, re-fetch that one PR directly (`fetch_pr`) and recompute its status before deciding anything. Close the follow-up only when that fresh read proves it addressed (`reply`/`as-built`/`follow-up`) — remove the old "PR #{pr} is no longer open" branch entirely. If the PR can't be read at all (deleted, API error), leave the follow-up open rather than closing on a guess.

## Decisions for the owner

<!-- marvin:decisions -->
### recheck-depth: How deep should the merge-time fresh check go?
- [ ] A: One fresh check before any gate work (as planned) — covers the ~20s cache-refresh race described in the ticket; a decision answered *during* the multi-minute rebase+retest gate itself could still slip through (same residual risk `assertDecisions` already accepts today for the PR-body Decisions).
- [ ] B: A and also re-run the same check immediately before the literal `gh pr merge` call, after the gate finishes — closes the gate-duration race too, at the cost of one more `gh api graphql` call on every merge that actually reaches that point.

### vanished-followup: A follow-up ticket whose PR can't be re-fetched at all (deleted PR, repo gone, persistent API error)
- [ ] A: Leave it open forever (never close on a guess) — safest, but an orphaned ticket needs a person to notice and close it by hand eventually.
- [ ] B: Leave it open for `GRACE_HOURS`-style re-checks, then close it after N consecutive scans still can't read the PR, noting "could not confirm; closed after repeated unreadable reads" — bounded, but risks closing one that was actually still unaddressed if GitHub happened to be flaky for that long.

## Tests first

Python (`lib/tests/test_owner_decisions.py`):
1. `pr_built_status`: returns `built=True` for a PR with no owner-Decisions comment at all.
2. `pr_built_status`: returns `built=True, reason` naming `reply`/`as-built`/`follow-up` for each addressed case (reuse existing fixtures from the `pr_status` tests above).
3. `pr_built_status`: returns `built=False` for an unaddressed Decisions comment, with and without a commit after it (still not built — a commit alone isn't an answer, per the existing rule).
4. `pr_built_status`: GitHub unreadable (`fetch` fails) → `ok=False, built=False` — never a guess.
5. `request()`'s existing three tests (already written) still pass unchanged after the `_fresh_status` refactor — verifies the refactor is behavior-preserving.
6. `fetch_pr`: returns the per-PR dict for a merged/closed PR not in the open search results; returns `None` on an API error or a PR that truly doesn't exist.
7. **Rewrite** `test_follow_up_closes_when_the_pr_closes_but_not_when_the_list_was_cut_short` (it currently encodes the bug: closes an *unaddressed* follow-up purely because the PR left the open list) into:
   - a PR merges with its Decisions comment still unaddressed → the follow-up stays open (not closed as "no longer open").
   - the same merged PR later gets an `ADDRESSED_MARKER` reply → the follow-up closes, `why` says "addressed".
   - the PR list is truncated (`hasNextPage: true`) → nothing is re-fetched or closed (unchanged from today).
   - `fetch_pr` itself fails for that PR (simulated API error) → the follow-up stays open, nothing closed on a guess.
8. `test_two_macs_racing_end_with_exactly_one_open_follow_up` and the dedupe/"never refiled" tests still pass unchanged (AC4, no regression).

JS (`dashboard/test/owner_decisions_gate.test.js`, new, mirroring `decisions.test.js`'s `assertDecisions` describe block):
9. `assertOwnerDecisionsBuilt`: resolves when the script reports `built: true`.
10. Throws `OWNER_DECISIONS_UNBUILT` when the script reports `built: false`, naming the reason in the message.
11. Throws `OWNER_DECISIONS_UNCHECKED` when `exec` rejects, and when it resolves with unparsable/`ok: false` JSON — fails closed, same contract as `assertDecisions`'s `DECISIONS_UNCHECKED`.
12. A PR URL with no recognizable repo/number → resolves (no-op), matching how other gate steps treat an unparseable URL as "not this gate's problem."

JS (`dashboard/test/merge.test.js` or a new describe block in `decisions.test.js`, mirroring "mergePr refuses open decisions before any gate work or merge"):
13. `mergePrUnqueued` calls the new `ownerDecisionsBuilt` dep after `decisions` and before `shouldGateMerge`/any rebase work, and a thrown `OWNER_DECISIONS_UNBUILT` stops the merge there (no gate work run, confirmed via a `shouldGate` spy never being called).

JS (`dashboard/test/merge_queue.test.js`, mirroring the existing `GATE_INFRA` hold tests):
14. `outcomeFor(refuse('OWNER_DECISIONS_UNBUILT'))` → `{ kind: 'hold', until: 'later' }`; the queue holds the PR (stays in `store.items`, not dropped into `failed`) and a later re-approve forces another try, matching the `GATE_INFRA` test pattern exactly.
15. **The literal AC1 scenario** — "Approve, then answer, then a merge that runs before the cache refresh: the PR is held, not merged" — build a small integration test: `createQueueLoader`'s `unbuilt` closure returns an **empty** Set (simulating the stale, not-yet-refreshed cache) so `mergeOrder` picks the PR as `next`; wire `run` to go through a `mergePr`-shaped function with `ownerDecisionsBuilt` wired to a fake `exec` that reports `built: false`. Assert the merge never actually ran (`shouldGate`/the mock "merge" step is never invoked) and the queue's outcome is `hold`, not `merged`.

**Break-list coverage:** "answer lands while merging" → covered by test 15 (the stale-cache race is exactly the scenario fixed); "optional Decision answered after merge" → covered by tests 7's merged-PR re-check; "stacked PR merged by its base's after-steps" → no special code path exists for it (after-steps only rebase, never merge, confirmed by reading `merge.js`), so it is covered by the same universal gate in test 13, no separate test needed; "GitHub unreadable at merge time: hold, never merge on a guess" → covered by test 11/14 (`OWNER_DECISIONS_UNCHECKED` → hold, not merged, not failed-out).

## Task List

1. `lib/owner_decisions.py`: extract `_fresh_status`, add `pr_built_status`, add `fetch_pr` + its single-PR GraphQL query, add `status` CLI subcommand; write tests 1–6.
2. `lib/owner_decisions.py::sync()`: replace the "no longer open" close branch with the fresh re-check via `fetch_pr`; rewrite test 7, confirm test 8 (AC4) still passes.
3. New `dashboard/webhook-server/owner_decisions_gate.js` (`assertOwnerDecisionsBuilt`); write tests 9–12.
4. Wire it into `merge.js::mergePrUnqueued`'s `deps`/call sequence; write test 13.
5. Add `OWNER_DECISIONS_UNCHECKED`/`OWNER_DECISIONS_UNBUILT` to `merge_order.js::HOLD_UNTIL`; write tests 14–15.
6. Update `docs/agents/decisions-format.md`'s "After the owner answers" section and `CONTEXT.md`'s "Answers not built yet" / "Owner decisions waiting on MARVIN" bullets to describe the merge-time fresh check and the merged-PR re-check (doc-first convention, both already describe this exact mechanism).
7. Run the full Python and dashboard suites (not just the touched files) before opening the PR, per the "full suites before a hand-merge" rule — this is a merge-gate change, a regression here breaks every future merge.
8. Open the PR with the Decisions section above, naming ticket #1261 and linking the two prior failed-verification comments as context for reviewers.