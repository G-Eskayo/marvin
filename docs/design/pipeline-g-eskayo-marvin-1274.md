## North-star fit

**Reuses:** the entire merge-queue/conflict machinery already built for marvin#231/#225/#314/#1097/#1183 — `mergeOrder`/`ownReason`/`enrichForOrder` (`dashboard/webhook-server/merge_order.js`), the pure-function-shared-by-both-Macs pattern (`dashboard/electron/main/mr_review.js:queueLines`), the per-head-commit dedup pattern (`conflictHead`/`conflictTold` in `merge_queue.js`, `_flagged_before`/`_mark_flagged` in `lib/ticket_pipeline.py`), the event-triggered (never-timer) `onWaiting`→`triggerTicketPipeline()` hook in `dashboard/webhook-server/index.js:446-452`, and the existing cheap-fix-before-rebuild path (`lib/conflict_repair.py`, called from `_try_conflict_repair`). No new polling, no new storage format, no new process.

**Why simplest-sufficient:** tracing the ticket's own repro (PR #1256) against the code shows most of "What to build" bullet 2 (trigger a rebase on a post-approval conflict) is *already wired* — `onWaiting` already fires `triggerTicketPipeline()` once per head commit whenever a queued PR's `entry.conflict` is true. The actual gap is narrower and is proven by a currently-passing test that encodes the bug: `lib/tests/test_ticket_pipeline.py:769` `test_a_pr_with_no_ticket_reference_is_left_alone` asserts a conflicting PR with **no `Closes #N` reference** gets no repair attempt and no comment — `_requeue_conflicted_prs` bails out at its very first line (`if not m or ...: continue`) before reaching the hand-made-PR flagging logic that already exists for ticket-linked hand-made PRs (lines 380-389). PR #1256 ("Parked choices") is exactly this case: a hand-authored PR with no ticket reference, so nothing in the pipeline ever looked at it again — matching "the webhook log never mentions it." The fix is to extend the existing hand-made-flag/repair path to ticketless PRs, not to build a new mechanism.

**Where it spends new work:** (a) the reason-string/"Held:" + conflicting-files wording in `ownReason()`, fed by data that mostly already exists (`rebaseStatus[].files` from `post_merge_rebase.js`, `conflict-repair.json`'s already-recorded-but-currently-discarded `files` field); (b) a small, genuinely new safety property — a model-assisted mechanical fix must not let a previously-approved PR merge un-reviewed, so a `needs-reapproval` PR label is introduced and read into `mergeOrder` the same way `repairFailed`/`conflictHead` already are; (c) one more `gh pr comment` call beside the existing `notify.py` call in `onStuck`.

**Tokens:** spends a little extra per-scan git/API work only for PRs that are actually conflicting (a small set); no new per-tick cost for the common (non-conflicting) case. No new background jobs.

**Leaves the user more capable:** today the owner either waits on something that will never move, or (if a real conflict needed a model's help) could unknowingly ship model-written conflict resolution without having seen it. Afterward the dashboard tells him exactly what's stuck, in what files, and surfaces a genuine re-approval step instead of silently trusting an automated edit — strictly more informative and more in his control, not more automated-and-passive.

**Machine:** webhook server + dashboard code only; no machine-placement question (same Mac Mini process that already runs the merge queue).

**Ticket's stated fit vs. code:** the ticket doesn't itself state a north-star fit section, so nothing to correct there.

## Decisions

<!-- marvin:decisions -->
### reapproval: A conflict repair that needed the model (not just a mechanical rebase) changed code the owner approved before seeing it. Should the PR need a fresh Approve before it can merge?
- [ ] A: Yes — label it `needs-reapproval`, pull it out of "queued" until Approve is pressed again (this plan's default)
- [ ] B: No — the merge gate's tests are the safety net; let it merge under the original Approve like a mechanical repair does today

### ticketless-escalation: A conflicting PR with no linked ticket (hand-made, no `Closes #N`) that MARVIN's cheap repair can't fix — how should it reach "the PR's author lane"?
- [ ] A: A comment on the PR itself, reusing the exact mechanism already built for ticket-linked hand-made PRs (`lib/ticket_pipeline.py:380-389`) — cheapest, one place to read it
- [ ] B: Also file a new GitHub issue assigned/labeled for a person, in addition to the PR comment — more visible, but a second place to look and a ticket with no code to attach to

## Tests (written first)

All in the existing files/styles already used for this code (`dashboard/test/merge_order.test.js`, `dashboard/test/merge_queue.test.js`, `dashboard/test/merge_queue_dashboard.test.jsx`, `dashboard/test/prState.test.js`, `lib/tests/test_ticket_pipeline.py`, `lib/tests/test_conflict_repair.py`).

From "How we'll try to break it":
1. A PR `CONFLICTING` from the moment it's listed (never attempted by the gate) *and* one that only becomes `conflict` later via `rebaseStatus` (post-merge check) both produce `reason` starting `Held: conflicts with main` — `merge_order.test.js`, extending the existing case at line 129-137.
2. After the resolver's push (new `headRefOid`), the hold clears and the PR keeps its original queue position — extend the existing test at `merge_order.test.js:145-147` to also assert `position`/`queuedAt` are unchanged, not just that it's "tried again."
3. A PR whose repair needed the model (`needs-reapproval` label present) reports `state: 'waiting'`, `queued: true`, reason `"needs your approval again…"`, and — critically — is **excluded from `order`/`next`/`runnable`** even though it's approved: `merge_order.test.js` new `describe`.

Misuse / adversarial cases the ticket's list didn't spell out:
4. `enrichForOrder` with `conflictFiles`/`rebaseStatus.files` absent, empty, non-array, or containing 50 entries — reason renders without "undefined"/a wall of text (apply the same truncate-and-count pattern already used for images in `prState.js:116-117`).
5. `readRepairFailures`-style readers given a malformed/missing `conflict-repair.json` (not JSON, not an object, `files` not an array) still return `{}`/`[]`, never throw — `merge_facts.test.js`.
6. GET `/merge-queue` still returns valid JSON when `conflict-repair.json` or `pr-rebase-status.json` is missing — `index.js` integration test (existing webhook test harness).
7. **Ticketless hand-made PR, real conflict**: flip `lib/tests/test_ticket_pipeline.py:769` `test_a_pr_with_no_ticket_reference_is_left_alone` — it must now attempt the cheap repair and, on failure, post the once-per-commit flag comment (reuse `_flagged_before`/`_mark_flagged` exactly as the existing hand-made test at line 1122 does), while still returning `[]` from `_requeue_conflicted_prs` (there is no ticket to send back).
8. Ticketless PR, repair succeeds mechanically → success comment posted, nothing else (no label).
9. Ticketless PR, repair succeeds but `model_assisted` → `needs-reapproval` label added + explanatory comment, creating the label first time it's needed (mirror the existing `needs-reengagement` create-then-retry fallback at `ticket_pipeline.py:399-401`).
10. Ticketless PR, repair returns `outcome: 'later'` (budget exhausted) → no comment, no flag, no mark — tried again next scan, not falsely flagged as unfixable.
11. Same commit scanned twice in quick succession (two triggers) → only one comment (dedup by sha via `_flagged_before`); a new push (new sha) → flagged again.
12. Existing ticket-linked, `pipeline/`-branch, hand-made, and already-sent-back behaviors (lines 697-1153 of the current test file) are unchanged — regression guard, run as-is.
13. `conflict_repair.repair()`'s returned dict for a *mechanical* resolution (`both_inserted`/`already_on_base`, no model call) carries `model_assisted: False`; for a genuine-hunk model-assisted fix it carries `model_assisted: True` — new assertions on `test_both_sides_add_to_list_with_model_assist` (`lib/tests/test_conflict_repair.py:130`) and a new mechanical-only case.
14. `_try_conflict_repair` crashing (`except Exception`) on a ticketless PR must not abort the whole scan or mis-flag the PR as a real conflict — mirror the existing crash-fallback test (`test_a_crash_inside_repair_still_falls_back_to_a_rebuild`).
15. Concurrency: two overlapping `evaluate()` calls on the Node side are already serialized by the `busy`/`again` guard in `merge_queue.js`; confirm no new reentrancy path is introduced (no new test needed beyond re-running the existing concurrency test with the changed `ownReason`).
16. `onStuck`'s new `gh pr comment` call: posts once per `conflictTold` firing (already deduped upstream, 24h-per-commit), includes conflicting files when known, and a failure to post (gh down) doesn't throw or block the queue (`.catch`) — `index.js`/webhook-server test.
17. **`SAID_BY_HEADLINE` regression**: a conflicting PR that is *not yet approved* (`mq.queued` false, headline "Conflicts with main…") must still show the queue line exactly once, not twice, now that the reason text starts with `Held: conflicts with…` — update the regex and the existing assertion at `merge_queue_dashboard.test.jsx:112`.
18. An approved-and-queued conflicting PR (`mq.queued` true, headline "Approved: in the merge queue") shows the new `Held: conflicts with main (files)` queue line beneath it — new `prState.test.js`/`merge_queue_dashboard.test.jsx` case, since this path was never gated by `SAID_BY_HEADLINE` (kind is `in-queue`, not `conflict`).

## Task List

1. **`lib/conflict_repair.py`**: add `"model_assisted": bool(resolved.get("model_assisted"))` to `repair()`'s success return dict (currently only mentioned inside the free-text `detail`).
2. **`lib/ticket_pipeline.py`**: extract the existing hand-made-PR flag comment (lines 380-389) into a small `_flag_hand_made(gh, repo, pr, files)` helper; add a `_flag_needs_reapproval(gh, repo, pr)` helper (label create-then-retry like `needs-reengagement`, plus an explanatory comment) — gated by Decision `reapproval`. Restructure `_requeue_conflicted_prs` so a PR with no `Closes`/`Fixes` reference that is `CONFLICTING` still goes through `_try_conflict_repair`, then either (a) success-mechanical → success comment, (b) success-model-assisted → success comment + `_flag_needs_reapproval` (if Decision A), (c) `rebuild`/real-conflict → `_flag_hand_made`, (d) `later` → skip silently. Also apply `_flag_needs_reapproval` to the existing ticket-linked repaired branches (lines ~358, ~372) when `model_assisted`.
3. **`lib/tests/test_ticket_pipeline.py`**: flip `test_a_pr_with_no_ticket_reference_is_left_alone`; add the new ticketless-repair tests (items 7-11 above); add `needs-reapproval` label-flow tests for both ticketless and ticket-linked PRs.
4. **`lib/tests/test_conflict_repair.py`**: add `model_assisted` field assertions (item 13).
5. **`dashboard/webhook-server/merge_facts.js`**: add `"labels"` to `PR_FIELDS`; extend `readRepairFailures()` (or add a sibling `readRepairFiles()`) to also expose each entry's `files` from `conflict-repair.json`; thread the new map into `createQueueLoader`'s `enrichForOrder` call.
6. **`dashboard/webhook-server/merge_order.js`**: in `enrichForOrder`, compute `needsReapproval` from PR labels (reusing `labelNames()`) and `conflictFiles` (prefer `rebaseStatus[].files`, fall back to the repair-state files map when the sha matches, like `repairFailed` already does). In `ownReason`, add the `needsReapproval` branch (ranked before the conflict branch) and rewrite the conflict branch's message to `Held: conflicts with ${base}${after}${filesSuffix} · ${...}` with a sensible file-list truncation for large lists.
7. **`dashboard/test/merge_order.test.js`**: update existing conflict-reason assertions to the new `Held:` wording; add the new cases (1, 3, 4) above.
8. **`dashboard/src/lib/prState.js`**: update `SAID_BY_HEADLINE.conflict` to match the new `Held: conflicts with` prefix.
9. **`dashboard/test/merge_queue_dashboard.test.jsx` / `dashboard/test/prState.test.js`**: update the affected assertion (item 17) and add the queued-and-held case (item 18).
10. **`dashboard/webhook-server/index.js`**: in `onStuck`, add a fire-and-forget `gh pr comment` call carrying the same message as the existing `notify.py` push, including conflicting files when known (fail-soft, matching the existing `.catch(() => {})` comment pattern used elsewhere in this file).
11. **webhook-server tests**: cover item 16 (comment posted alongside notify, failure doesn't throw) and item 6 (GET `/merge-queue` resilient to missing state files).
12. **`CONTEXT.md`**: update the "cheap fix before any rebuild" (#314) paragraph to note the hand-made flag now applies whether or not the PR carries a ticket reference, and note the new `needs-reapproval` label/behavior if Decision `reapproval` is A.
13. Run the full Python + dashboard (vitest) suites before opening the PR (per "Full suites before a hand-merge").