Now I'll write the plan.

## North-star fit

**Reuses, nothing new added:** `ownReason`/`enrichForOrder`/`mergeOrder` in `dashboard/webhook-server/merge_order.js` (marvin#231's single order implementation shared by the webhook server and every dashboard client); `markConflict`/`conflictTold`/`onWaiting`/`onStuck` in `dashboard/webhook-server/merge_queue.js` (marvin#1183/#1184's hold-and-tell-once machinery); the post-merge conflict check's `files` field in `dashboard/webhook-server/rebase_status.js`/`post_merge_rebase.js` (#225, computed via `merge.js`'s `conflictsWithBase`, triggered on the merge event, never a timer); `conflict_repair.py`'s `conflicted_files()` (`git merge-tree`) already persisted per-PR in `~/.claude/logs/conflict-repair.json`; the existing fail-soft `gh pr comment ... .catch(() => {})` pattern at `dashboard/webhook-server/merge.js:1009`; the file-capping convention already used for `needsImages` in `dashboard/src/lib/prState.js` (`files.slice(0, 3).join(', ') + "and N more"`).

**Already built — confirmed by reading the code, not assumed:**
- The "triggers a rebase... once per head commit, on the event" AC is already satisfied: `onWaiting` in `index.js:447-454` calls `triggerTicketPipeline()` the first time an entry shows `conflict: true` for a given `headRefOid` (`triggeredResolver` map), which runs the ticket pipeline's conflict-repair step. No timer anywhere in this path.
- "After the rebase is pushed, the hold clears and the PR keeps its original place" already works: `markConflict` only ever changes `conflictHead`/`conflictAt`; it never touches `approvedAt`, so a resolved conflict's PR keeps its queue position. Covered by the existing test at `dashboard/test/merge_queue.test.js:160-186`.

**What's actually missing, and why it's the simplest sufficient fix:** `ownReason()` already says `"conflicts with main · MARVIN is fixing it"` for a held conflict — the information exists, it just isn't labeled "Held:" and drops the file list that is *already computed twice over* and then thrown away: `readRepairFailures()` in `merge_facts.js:28-33` reads `conflict-repair.json` but keeps only `failed_sha`, discarding its `files` field, and `enrichForOrder` never reads `rebaseStatus[url].files` at all even though that's already on every PR's rebase status. The fix threads two already-computed fields through; it computes nothing new. The once-a-day `onStuck` notice (`index.js:456-464`) only fires a desktop notification (`notify.py`) — one more fail-soft `gh pr comment` call, identical in shape to the pattern already used three times elsewhere, makes it land on the PR too.

**Tokens/compute:** zero new GitHub calls, zero new git operations. One extra `readJson` of a file already on disk per `/merge-queue` request, and one extra `gh pr comment` call, at most once per PR per day it's stuck (bounded, rare, through the existing PATH `gh` gate).

**Phone-OS direction:** makes the queue's state legible from anywhere the owner looks — dashboard card, `GET /merge-queue` consumers (including the phone), and now the PR itself on GitHub/GitHub mobile — the "reachable from anywhere" criterion.

**Leaves the owner more capable, not more passive:** he stops having to intuit that "in the merge queue" might silently mean "stuck forever"; he sees why, which files, and gets a record even when he isn't looking at the dashboard.

**Machine:** all touched files live in `dashboard/webhook-server/`, `dashboard/electron/main/` and `dashboard/src/lib/`, which already run on whichever Mac hosts the merge webhook — no machine-specific concerns.

**Prior attempts:** two WIP snapshots for this same ticket exist as rescue refs (`refs/rescue/.../1274/...`), preserved before redispatch — not completed/merged PRs, just abandoned work-in-progress. The most recent one (`72d0e175`) converges almost exactly on this same design, independently re-derived here by reading the current code rather than that diff. I treat its convergence as confirmation, not as something to copy uninspected — I re-verified every claim against current `main`.

## Decisions

<!-- marvin:decisions -->
### stale_review: What should count as "the rebase needs your re-approval (stale review)," if anything?
- [ ] A: Nothing new — the existing rule stands (CONTEXT.md: a new commit on a queued PR, mechanical or conflict-fix alike, is retested and merges without re-approval). This clause of the AC is then vacuously satisfied: it never fires, and the card always just returns to "queued." No new code.
- [ ] B: Only when `conflict_repair.py`'s **model-assisted** resolution (the LLM-edited-hunks path, not the mechanical generated-files/both-sides-added path) produced the push, since that changed real code rather than just moving it. The card then says "Held: needs your re-approval" instead of "queued" until re-approved. Needs new plumbing: `conflict_repair.py` recording that a *successful* repair was model-assisted (today it only records `files`/`reason` on failure), a new hold reason in `merge_order.js`, and a way to clear it on re-approve.
- [ ] C: Same as B, but only for a **hand-made PR** (no ticket ref) — a stranger's commits shouldn't silently keep an existing Approve's blessing, where a pipeline-authored rebuild already goes through its own rebuild/re-open flow regardless.

If A is picked, nothing further is built for this clause in this PR. If B or C, that plumbing becomes its own follow-up ticket rather than part of this change, to keep this PR small and reviewable — I found no existing precedent anywhere in the repo for "stale review" (grepped for `reviewDecision`/`stale review`/`re-approv`) to build on safely without an answer.

## Tests (written first)

All in existing files, following their established style — pure-function tests in `merge_order.test.js`/`merge_queue.test.js`, an injected-dependency test in `merge_queue_main_state.test.js` for the loader wiring, and dashboard-rendering tests in `pr_state.test.js`/`merge_queue_dashboard.test.jsx`.

**From "How we'll try to break it":**
1. A PR already `mergeable: 'CONFLICTING'` the moment it's approved (never went through a post-merge check) → its entry's `reason` starts with `"Held: conflicts with main"` immediately, and `mergeOrder().next` never picks it (new case in `merge_queue.test.js`, started conflicting rather than becoming conflicting).
2. A PR that becomes conflicting *after* being queued (existing test at `merge_queue.test.js:160-186`) → still says `"Held: ..."` — update the existing assertions, don't change the mechanism.
3. After the resolver's push, the hold clears and the PR keeps its queue position — already covered by the same existing test; update its string assertions only, no new behavior to test.
4. Stale-review clause → deferred to the Decision above; no test until it's answered (A needs none).

**Misuse cases the ticket's list missed:**
5. Conflict files present via `conflict_repair.json`'s record, matching the PR's **current** `headRefOid` → shown in the reason, e.g. `"Held: conflicts with main after #970 · needs a rebuild (a.js, b.js)"` (new case, `merge_order.test.js`).
6. A repair-failure record for an **older** commit (stale, mirrors the existing "old sha" test at `merge_order.test.js:171`) → its files are ignored, same as its `reason` already is today (extend that existing test, don't add files).
7. No repair record, but the post-merge check's `rebaseStatus[url].files` has files → shown (new case: conflict detected via #225's check, before any resolver attempt).
8. Neither source has files (`rebaseStatus[url].files` missing/`undefined`/empty, no repair record) → no `(...)` suffix, no crash (new case).
9. A huge file list (5+ files) → capped to first 3 + `"and N more"`, matching `prState.js`'s `needsImages` convention exactly (new case).
10. A non-queued (not-yet-approved) conflicting PR → `entries[url].reason` stays **unprefixed** (`"conflicts with main..."`, no `"Held:"`), so `pr.conflicts`' own card headline and the `SAID_BY_HEADLINE.conflict` suppression regex still behave correctly — this is the regression risk a careless fix could trip (new end-to-end case through `queueLineFor()` in `merge_queue_dashboard.test.jsx`, proving the queued/unqueued cases side by side).
11. `createQueueLoader`'s new `repairFiles` param defaults to reading `conflict-repair.json` itself, but a test-injected one is used instead and the default is never called (new case in `merge_queue_main_state.test.js`, mirroring the existing `repairs`/`rebase` injection style already there).
12. `stuckConflictNote(prNumber, days)` (new pure function, extracted so the comment text is unit-tested rather than embedded untested in `index.js`, matching how `holdReason`/`retryAt` are already tested): singular "1 day" vs plural "N days" (new cases in `merge_queue.test.js`).
13. The `gh pr comment` call in `onStuck` failing (network, auth, rate-limited) must not block the existing desktop notification or throw inside the queue's trigger path — verified by code inspection matching the identical, already-proven `.catch(() => {})` pattern at `merge.js:1009` (documented, not newly tested, same as that existing call has no dedicated test either).
14. `GET /merge-queue`'s `facts.repairFiles` round-trips correctly when `conflict-repair.json` is malformed/missing (reuses `readJson`'s existing fallback-to-`{}` behavior; one assertion alongside the existing `readRepairFailures` coverage).

## Task List

1. `dashboard/webhook-server/merge_facts.js`: add `readRepairFiles()` next to `readRepairFailures()` — same read of `conflict-repair.json`, returns `{ "repo#n": { sha, files } }` only for entries with a non-empty `files` array. Add a `repairFiles = readRepairFiles` default param to `createQueueLoader`, passed through to `enrichForOrder`.
2. `dashboard/webhook-server/merge_order.js`: add `repairFiles` param to `enrichForOrder`; compute `conflictFiles` per PR — the repair record's files when its `sha` matches the current `headRefOid` and is non-empty, else `rebaseStatus[url].files` when non-empty, else `null`. In `ownReason`, when `pr.conflict`, append a capped file list (first 3 + `"and N more"`, reusing the existing `short()` truncation) to the status clause. In `mergeOrder`'s entry construction, prefix `reason` with `"Held: "` only when `why.conflict && queued` (the per-PR `queued` flag already computed in that loop) — leave the non-queued (`pr.conflicts`, pre-approval) path's reason text untouched.
3. `dashboard/webhook-server/index.js`: import `readRepairFiles` and `stuckConflictNote`; add `repairFiles: readRepairFiles()` to the `/merge-queue` response's `facts` object; in `onStuck`, add a second fail-soft call (`execAsync('gh', ['pr', 'comment', pr.url, '--body', stuckConflictNote(pr.number, days)]).catch(() => {})`) alongside the existing `notify.py` call.
4. `dashboard/webhook-server/merge_queue.js`: add and export `stuckConflictNote(prNumber, days)` — pure string formatter, singular/plural days.
5. `dashboard/electron/main/mr_review.js`: thread `facts.repairFiles || {}` into the `enrichForOrder` call inside `queueLines()`, next to the existing `repairFailed` param.
6. `dashboard/src/lib/prState.js`: update `SAID_BY_HEADLINE.conflict` from `/^conflicts with\b/` to `/^(?:Held: )?conflicts with\b/` so the queue-line dedup still suppresses correctly against the new prefixed text for a queued PR, while the unprefixed pre-approval text still matches too.
7. Write the tests in the "Tests" section above, in `dashboard/test/merge_order.test.js`, `merge_queue.test.js`, `merge_queue_main_state.test.js`, and `merge_queue_dashboard.test.jsx`; update the existing string assertions at `merge_order.test.js:167-183` and `merge_queue.test.js:178` for the new `"Held: "` prefix.
8. `CONTEXT.md`: update the "Queue line" bullet's example (`"conflicts with main after #970 · MARVIN is fixing it"` → `"Held: conflicts with main after #970 · MARVIN is fixing it"`) and add one sentence noting the conflicting-file list and the day-stuck PR comment, next to the existing "Queue line, once" and "One card, both states" bullets.
9. Run the full `npm test` suite in `dashboard/` (no Python-side behavior changes — `conflict_repair.py`'s output shape is only read, never changed) before opening the PR, and carry the Decision above in the PR body per `docs/agents/decisions-format.md`.