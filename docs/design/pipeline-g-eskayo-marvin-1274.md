## North-star fit

**Reuses:** `mergeOrder`/`enrichForOrder`/`ownReason` in `dashboard/webhook-server/merge_order.js` (marvin#231's "one implementation for both" — the webhook server and every dashboard/Electron client compute the same queue-line text from the same facts; marvin#1183's `markConflict`/`conflictTold`/`onStuck` in `merge_queue.js`; the post-merge conflict check's `files` field in `rebase_status.js`/`post_merge_rebase.js` (#225, computed via `git merge-tree`, triggered on the merge event, not a timer); `conflict_repair.py`'s `conflicted_files()`/`attempt()` state in `conflict-repair.json`; the existing `gh pr comment ... .catch(() => {})` fail-soft pattern already used three times in `merge.js`/`deny.js`; the file-capping convention already used by `needsImages` in `prState.js` (first 3, "and N more").

**Already built, nothing to add:** marvin#1183/#1184 (merged via PR #1186) already give conflicting PRs a hold that survives across merges (`markConflict`), a once-per-head-commit trigger of the conflict resolver on the event (`triggeredResolver` in `index.js`, keyed by `headRefOid`, fired from `onWaiting`), and a once-per-commit "stuck" notice after a day (`onStuck`). Ticket #1274's AC "a conflict... triggers a rebase... once per head commit, on the event" and "after the rebase is pushed, the hold clears and the PR keeps its place" are **already satisfied by this code** — confirmed by reading `index.js:433-463`, `merge_queue.js`'s `markConflict`/`evaluate()`, and existing tests (`merge_queue.test.js:169-184`, `:515-536`). No change needed there.

**What's actually missing, and the simplest sufficient fix:** the queue's own conflict text (`ownReason` in `merge_order.js`) says `"conflicts with main · MARVIN is fixing it"` — no "Held:" prefix and no files, even though the file list is already computed twice over (post-merge check's `rebaseStatus[url].files`, and `conflict_repair.py`'s `conflicted_files()` persisted in `conflict-repair.json`) and then **dropped on the floor**: `readRepairFailures()` in `merge_facts.js` reads `conflict-repair.json` but discards its `files` field, and `enrichForOrder` never reads `rebaseStatus[url].files` at all. The fix threads existing data through, it doesn't compute anything new. And the day-late "stuck" notice (`onStuck` in `index.js`) only calls `notify.py` (a desktop notification); it needs one more fail-soft `gh pr comment` call, same pattern already used elsewhere.

**Tokens/compute:** spends nothing new at runtime — no new GitHub calls, no new git operations; it's wiring already-computed facts through. The only new runtime cost is one extra tiny `readJson` of a file already on disk, and one extra `gh pr comment` call once per PR per day it's stuck (bounded, rare).

**Phone-OS direction:** makes the merge queue's state legible from anywhere the owner looks (dashboard card, `GET /merge-queue`-fed clients, and now the PR itself on GitHub.com/GitHub mobile) — exactly the "reachable from anywhere" criterion.

**Leaves the owner more capable, not more passive:** he no longer has to intuit "in the merge queue" might mean "silently stuck forever"; he sees why, what files, and gets a GitHub-side record even when he's not looking at the dashboard.

**Machine:** none of this is machine-specific; all changes are in `dashboard/webhook-server/` and `dashboard/electron/main/`, which already run on whichever Mac runs the merge webhook.

## Decisions

One part of the ticket has no precedent anywhere in this codebase and no safe default I'm willing to guess: "stale review." I grepped the whole repo for `reviewDecision`/`stale review`/`re-approv` — this pipeline doesn't use GitHub's native review-approval gate at all (the merge gate just calls `gh pr merge` directly), and MARVIN's own "Approve" queue has a settled, opposite rule already written down in CONTEXT.md ("new commits on a queued PR keep its place too, and the new commit is what gets tested" — no re-approval, ever). Building new re-approval plumbing on a guess is exactly the kind of thing that likely caused one of the two prior failed attempts on this ticket to "regress." So:

<!-- marvin:decisions -->
### stale_review: What should count as "the rebase needs your re-approval (stale review)," if anything?
- [ ] A: Nothing new. The existing rule stands — any new commit on a queued PR (mechanical rebase or model-assisted conflict fix alike) is retested and merges without re-approval. This clause of the AC is then vacuously satisfied: it never fires, and the card always just returns to "queued." (No new code.)
- [ ] B: Only when `conflict_repair.py`'s **model-assisted** resolution (the LLM-edited-hunks path, not the mechanical generated-files/both-sides-only-added path) produced the push — because that push changed real code, not just moved it. The card then says "Held: needs your re-approval" instead of "queued" until you approve again. Needs new plumbing: `conflict_repair.py` records when a *successful* repair was model-assisted (today it only records `files`/`reason` on *failure*), the queue holds on that commit, and pressing Approve again clears it.
- [ ] C: Same as B, but only for a **hand-made PR** (no ticket ref — not pipeline-authored): a stranger's commits shouldn't silently keep your existing Approve's blessing, where a pipeline-authored rebuild already goes through its own rebuild/re-open flow regardless.

If A: nothing further to build for this clause. If B or C: this becomes its own follow-up (new state in `conflict-repair.json`, a new hold reason in `merge_order.js`, a new card string) rather than part of this PR, to keep this change small and reviewable.

## Tests (written first)

All in existing files, following their established style (pure-function tests for `merge_order.js`/`merge_queue.js`, injected-dependency tests for `merge_facts.js`'s `createQueueLoader`, and one end-to-end test through `queueLines()` for the regression risk below).

**From "How we'll try to break it":**
1. A PR already `mergeable: 'CONFLICTING'` the moment it's approved (never went through a post-merge check) → `entries[url].reason` is `"Held: conflicts with main..."` immediately, and it is never picked for `run()` (new test in `merge_queue.test.js`, mirroring the existing resolver test at line 169 but starting conflicting instead of becoming conflicting).
2. A PR that becomes conflicting *after* being queued (existing test at `merge_queue.test.js:169-184`) → still says `"Held: ..."` (update the existing assertion).
3. After the resolver's push, the hold clears and the PR keeps its queue position (existing test at `merge_queue_test.js:180-183`/`merge_order.test.js:175-178,180-183` already cover this; update their string assertions, no new test needed since the mechanism itself is unchanged).
4. Stale-review clause: deferred to the Decision above — no test until it's answered (A needs none; B/C would need their own).

**Misuse cases the ticket's list missed:**
5. Conflict files present via `rebaseStatus[url].files` → shown in the reason, e.g. `"Held: conflicts with main after #970 (a.js, b.js) · MARVIN is fixing it"` (new `merge_order.test.js` case).
6. Conflict files present via `conflict-repair.json`'s failed-repair record, validated against the **current** `headRefOid` → shown (new case).
7. A repair-failure record for an **older** commit (stale, like the existing "old sha" test at line 171) → its files are ignored, same as its `reason` already is today (extend that existing test).
8. `rebaseStatus[url].files` missing, `undefined`, or not an array → no crash, no `(...)` suffix (new case).
9. `rebaseStatus[url].files` is `[]` (empty, mergeable again before anyone looked) → no `(...)` suffix (new case).
10. A huge file list (8+ files) → capped to the first 3 + `"and N more"`, matching `prState.js`'s `needsImages` convention exactly, so the queue line never becomes a wall of filenames (new case).
11. Non-queued (not-yet-approved) conflicting PR → reason text stays **unprefixed** (`"conflicts with main..."`, no `"Held:"`), so the existing "Conflicts with main" card's own text and the `SAID_BY_HEADLINE.conflict` suppression regex (`merge_queue_dashboard.test.jsx:112`) still match. This is the regression risk one of the two prior attempts likely tripped on — add an explicit end-to-end test through `queueLines()`/`queueLineFor()` proving both the queued (prefixed) and non-queued (unprefixed, suppressed) cases side by side.
12. `createQueueLoader`'s new `repairFiles` param wired through to `enrichForOrder` (new case in `merge_queue_main_state.test.js`, mirroring the existing `repairs`/`rebase` injection style) — default (`readRepairFiles`) never called when a test injects its own, matching existing coverage.
13. `stuckConflictNote(days)` (new pure function, extracted from `index.js`'s `onStuck` so the message itself is unit-tested, matching how `holdReason`/`retryAt` are already tested rather than embedded untested in `index.js`): singular "1 day" vs plural "N days", and bad input (`0`, negative, non-finite) still returns sane text instead of throwing (new cases in `merge_queue.test.js`).
14. (Documented, not newly tested) `gh pr comment` failing when posting the stuck notice must not block the desktop notification or crash the webhook — verified by code inspection matching the identical already-proven `.catch(() => {})` pattern at `merge.js:1009`, consistent with how the existing `notify.py` call there has no dedicated test either.

## Task List

1. `dashboard/webhook-server/merge_facts.js`: add `readRepairFiles()` (reads the same `conflict-repair.json` as `readRepairFailures()`, returns `{ "repo#n": { sha, files } }` for entries with a non-empty `files`), and thread a `repairFiles = readRepairFiles` default param into `createQueueLoader`, passed to `enrichForOrder`.
2. `dashboard/webhook-server/merge_order.js`: add `repairFiles` param to `enrichForOrder`; compute `conflictFiles` per PR (repair-matching-current-head files first, else `rebaseStatus[url].files`, else `null`), guarding non-array/empty values; in `ownReason`, append a capped file list (`first 3, "and N more"`) to the conflict reason; in `mergeOrder`'s entries construction, prefix `reason` with `"Held: "` when `why.conflict && queued` (leave the non-queued path untouched).
3. `dashboard/webhook-server/index.js`: import `readRepairFiles`; add `repairFiles: readRepairFiles()` to the `/merge-queue` `facts` object; extract `stuckConflictNote(days)` into `merge_queue.js` and call it in `onStuck` to add a fail-soft `gh pr comment` alongside the existing desktop `notify.py` call.
4. `dashboard/webhook-server/merge_queue.js`: add and export `stuckConflictNote(days)`.
5. `dashboard/electron/main/mr_review.js`: thread `facts.repairFiles || {}` into `enrichForOrder` inside `queueLines()`.
6. Update existing string assertions in `dashboard/test/merge_order.test.js` (lines ~167-172, ~182) and `dashboard/test/merge_queue.test.js` (line ~178) for the new `"Held: "` prefix; add the new test cases listed above across `merge_order.test.js`, `merge_queue.test.js`, `merge_queue_main_state.test.js`, and `merge_queue_dashboard.test.jsx`.
7. `CONTEXT.md`: add a short bullet under "Merge queue" documenting the `"Held: conflicts with main (files)"` wording and the PR-comment addition to the day-stuck notice, next to the existing "Queue line" bullet.
8. Run the full suite (`npm test` in `dashboard/`, plus `pytest` if any Python-side expectations touch `conflict_repair.py`'s output shape — confirm none do, since I'm only reading its existing `files` field, not changing it) before opening the PR; carry the Decision above in the PR body per `docs/agents/decisions-format.md`.