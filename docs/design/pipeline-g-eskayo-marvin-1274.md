Good — confirmed `enrichForOrder` has exactly two callers (`merge_facts.js`'s `createQueueLoader`, and `mr_review.js`'s `queueLines`), both already identified. Now I have everything needed to write the plan.

## North-star fit

**Reuses, before adding anything new:**
- `merge_order.js:ownReason()` (conflict branch, line 157-160) already computes the per-PR conflict reason and `conflict: true` flag consumed by both the webhook server's internal queue view and the dashboard's own recompute (`mr_review.js:queueLines` calls the same `enrichForOrder`/`mergeOrder`). I extend this one function rather than adding a parallel path.
- `post_merge_rebase.js:checkOpenPrs` and `lib/conflict_repair.py:repair()`/`attempt()` already compute conflicting file names (`git merge-tree --name-only`) and persist them to `pr-rebase-status.json` and `conflict-repair.json` respectively. `merge_facts.js:readRepairFailures()` currently reads that file but **throws the `files` field away**, keeping only the sha. No new git/GitHub calls are needed anywhere — just stop discarding data already computed.
- `onWaiting`'s resolver trigger (`index.js:447-453`, keyed by `triggeredResolver: Map<url, headSha>`, firing `triggerTicketPipeline()`) and `ticket_pipeline.py`'s `_try_conflict_repair` → comment-on-hand-made-PR / send-ticket-back-for-pipeline-PR (lines 354-409) **already fully implement "What to build" bullet 2** (rebase triggered once per head commit, on the event). No new code there — only tests to confirm it, and one added log line (see below).
- `merge.js:triggerTicketPipeline(spawnFn)` is the established pattern for a small, independently-testable side-effecting export next to a webhook-server event hook (it already has its own describe block in `merge.test.js`). I follow that same pattern for the new "comment on the PR" side effect instead of leaving it as an untestable inline closure in `index.js`.
- `merge.js:1009`'s existing flaky-test PR comment (`exec('gh', ['pr', 'comment', prUrl, '--body', note]).catch(() => {})`) is the reused pattern for posting a fail-soft PR comment.
- `prState.js`'s existing `pr.conflicts` branch (lines 102-106) and `needsImages`' file-list truncation (`files.slice(0, 3).join(', ') + ' and N more'`) are reused conventions for wording and truncation, rather than inventing new UI text rules.

**Root cause, found by reading the code (not assumed):** the bug isn't a missing feature — `dashboard/src/lib/prState.js:95-97` returns `'Approved: in the merge queue'` whenever `mq?.queued` is true, but `merge_order.js` sets `queued: true` even when `state: 'waiting'` (held on a conflict). So a held PR's own `conflict`/reason data (already computed) never gets read — it's masked by an earlier, too-broad check. This exactly matches the ticket's observed symptom (#1256 sitting as "in the merge queue" while #1257/#1273 merged past it) and explains "the webhook log never mentions it" (`onWaiting`'s conflict branch calls `triggerTicketPipeline()` but never `log(...)`, unlike its sibling `onStuck` path two lines below it).

**Simplicity:** the fix is almost entirely "stop discarding/masking data that's already computed" (three small edits: `readRepairFailures` keeps `files`, `enrichForOrder` surfaces `conflictFiles`, `ownReason` prepends "Held:" and appends the files) plus one genuinely new behavior (posting the existing stuck-notice text as a PR comment too) and one genuinely missing log line. No new services, no new storage, no new GitHub/git calls.

**Resource cost:** zero new git/GitHub calls per decision cycle (reuses already-computed `pr-rebase-status.json` / `conflict-repair.json` data); one new `gh pr comment` call, but only once per day per stuck PR (same cadence as the existing `onStuck` notify.py call it piggybacks on).

**Phone-OS direction:** none of this is Mac-only; it's pure data/wording flowing through `/merge-queue` and the dashboard's React layer, consistent with eventually being readable from Mobile too.

**User capability:** directly fixes a case where MARVIN silently did nothing while the owner was misled into thinking the machine was busy — strictly more capable/informed, not more passive.

**Machine:** no machine-placement question here; this is pure logic in the existing webhook-server/dashboard process on whichever Mac runs it.

## Decisions for the owner

None. Every open question resolved to an existing, already-decided pattern in the code (file-list truncation, "needs a rebuild" wording, comment being additive not a replacement for the desktop notify).

## Tests to write first

In `dashboard/test/merge_order.test.js`:
1. Update the three existing conflict-wording assertions (lines 167, 169, 172, 182) to the new `"Held: conflicts with main …"` text — a verify-fail otherwise, since behavior changes.
2. Conflicting **at approval time** (`mergeable: 'CONFLICTING'` from the first load, never previously queued clean) → `state: 'waiting'`, `reason` starts with `"Held: conflicts with main"`.
3. Becoming conflicting **after** approval (queued clean, then a later `evaluate()` sees `mergeable: 'CONFLICTING'` or a fresh `rebaseStatus` conflict entry) → same `"Held: conflicts with main"`, same shape as #2 (no special-casing by when).
4. Files surfaced from `rebaseStatus[url].files` when present.
5. Files surfaced from `repairFailed[repo#n].files` when the resolver already tried and failed on this exact head (sha match) — none when the sha is stale (a newer commit since the recorded failure).
6. No file list known yet (brand-new conflict, no rebaseStatus/repairFailed entry) → reason still says `"Held: conflicts with main"`, with no `"undefined"`/empty-list artifact.
7. Once the resolver pushes a new commit (`headRefOid` changes, `mergeable` goes back to non-CONFLICTING) → `state` returns to `'queued'`, and `position`/`approvedAt` are **unchanged** (same test shape as the existing "stale post-merge conflict is overruled" test, extended to assert original place in line).
8. Malformed/huge input: `rebaseStatus[url].files` not an array → treated as empty, no throw. A 200-file conflict list → reason truncates (reuse the `needsImages` 3-file-then-"and N more" convention) rather than producing a multi-KB string.

In `dashboard/test/merge_facts.test.js` (or wherever `readRepairFailures` is currently tested):
9. `readRepairFailures()` returns `{sha, files}` per key; `conflict-repair.json` with `files` missing/not-an-array/corrupt JSON degrades to `{sha, files: []}` / `{}` rather than throwing.

In `dashboard/test/merge_queue.test.js`:
10. `onWaiting`'s conflict branch now also calls the injected `log()` once per head commit (currently un-asserted) — a real behavior gap found while reading the code, not just a refactor check.
11. Concurrency: two overlapping `kick()`/`evaluate()` calls for the same repo while a conflict is held still trigger the resolver exactly once per head commit (existing `busy`/`again` serialization; extend the existing test at line 173 to call `drain`/`kick` twice back-to-back).
12. A PR dropped from `openPrs` (closed/merged elsewhere) between being marked held and the next `evaluate()` never fires `onWaiting` for it (guarded by `dropped` filtering already existing — write the test, don't add code if it already passes).

In `dashboard/test/merge.test.js` (next to the existing `describe('triggerTicketPipeline', ...)`):
13. New exported `notifyConflictStuck(repo, pr, info, { exec, notify })` (replacing the inline closure currently only in `index.js`): posts a `gh pr comment` on `pr.url` with the stuck message; the existing notify.py call still fires too (additive, not a replacement).
14. `gh pr comment` rejecting (bad credentials, PR locked, repo archived, network down) is swallowed — the notifier never throws, matching the `.catch(() => {})` convention at `merge.js:1009`.
15. Called twice for the same `(repo, pr, since)` — since `onStuck` is itself already only invoked once per commit by `createMergeQueue`'s `conflictTold` gate, this is really "does the new function itself have any hidden state that could double-post" — assert it's pure/stateless (no second comment unless called a second time).

In `dashboard/test/prState.test.js`:
16. A PR with `mergeQueue: {queued: true, state: 'waiting', conflict: true, reason: 'Held: conflicts with main …'}` → `kind: 'conflict'`, headline starts with `"Held: conflicts with"` — **not** `'in-queue'`/`"Approved: in the merge queue"` (this is the regression test for the actual root-cause bug in #1274).
17. A PR with `mergeQueue: {queued: true, state: 'queued'}` (no conflict) → unchanged, still `'in-queue'` (guards against breaking the normal case while fixing the masked one).
18. A PR with `mergeQueue: {queued: true, state: 'waiting', conflict: false}` for an unrelated hold reason (decisions pending / main red / checks failing) → falls through to its own correct existing kind (`needs-options`/`decisions-pending`/`checks-failed`/etc.), not `'in-queue'` and not wrongly `'conflict'` either — the generalized-fix regression test.
19. `SAID_BY_HEADLINE.conflict` still matches the new `"Held: conflicts with main"` wording so `WorkshopTab`'s `queueReason()` doesn't render the same sentence twice on one row (companion test in `dashboard/test/*WorkshopTab*` or wherever `metaFor`/`queueReason` is tested today).

In `dashboard/test/next_step.test.js`:
20. `kind === 'conflict'` with the new wording still correctly branches to `'Needs a rebuild'` (when the reason contains `"needs a rebuild"`) vs `'Fixing a conflict'` — confirms the substring contract survives the wording change; this is the "verify fails when code changes without a test changing" case for `next_step.js`, which itself needs **no code change**.

**Misuse categories from the global checklist not already covered above:** bad/huge input (#8, #9), a dependency failing (`gh pr comment` down, #14), repeats/concurrency (#11, #15), stale state (#5, #7), a person's mistake (a hand-rebase that's still conflicting gets a fresh `headRefOid` and re-triggers the resolver once for the new commit — covered implicitly by #3's "becomes conflicting" shape plus #11's per-commit dedup key).

## Task List

1. `merge_facts.js`: change `readRepairFailures()` to return `{ [repo#n]: { sha, files } }` instead of `{ [repo#n]: sha }`, defaulting `files` to `[]` on anything malformed.
2. `merge_order.js` `enrichForOrder()`: update the `repairFailed` comparison to `repairFailed?.[key]?.sha === p.headRefOid`, and add `conflictFiles: rbConflict ? (rb.files || []) : (repairFailed?.[key]?.sha === p.headRefOid ? repairFailed[key].files : null)` (or equivalent) onto the enriched PR.
3. `merge_order.js` `ownReason()`: change the `pr.conflict` branch to produce `"Held: conflicts with ${base}${after}"` + a truncated file list (reuse the 3-file "and N more" convention) + the existing `"needs a rebuild"` / `"MARVIN is fixing it"` suffix, keeping the exact substring `"needs a rebuild"` intact for `next_step.js`'s regex.
4. Update the three pre-existing wording assertions in `merge_order.test.js` to match, then add the new tests (#2-#8 above).
5. Add tests for `readRepairFailures()`'s new shape (#9), then implement if any gap surfaces.
6. `index.js`: add a `log(...)` call in `onWaiting`'s conflict branch (currently silent — the actual "webhook log never mentions it" gap from the ticket's Task description).
7. `merge.js`: extract `export function notifyConflictStuck(repo, pr, info, { exec = execFileAsync, notify = ... } = {})` that keeps the existing notify.py desktop call and adds a fail-soft `gh pr comment` on `pr.url` with the same message; wire `index.js`'s `onStuck` to call it.
8. Add tests #13-#15 for `notifyConflictStuck`, then the `merge_queue.test.js` tests #10-#12.
9. `prState.js`: add the new `mq.state === 'waiting' && mq.conflict` branch (headline `"Held: conflicts with ${main}"`) ahead of the generic `mq?.queued` branch; narrow that generic branch to `mq.state !== 'waiting'`; widen `SAID_BY_HEADLINE.conflict` to match the new wording.
10. Add/extend `prState.test.js` tests #16-#19, and `next_step.test.js` test #20 (expected to pass unchanged — confirms no collateral damage).
11. Run the full `dashboard` vitest suite and the Python suite once, locally, before considering this done — three prior automated attempts on this ticket failed on commit/verify/timeout issues, not necessarily on code correctness, so keep this diff to exactly the files above and avoid anything that lengthens the test run (no new slow/integration tests, no new npm deps).