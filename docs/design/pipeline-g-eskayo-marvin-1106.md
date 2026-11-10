## North-star fit

**Reuses:** the merge queue's own persistence (`dashboard/webhook-server/merge_queue.js` `createQueueStore`/`createMergeQueue.approve`/`evaluate`'s `dropped` logic) — an item a crashed process never resolved stays in `~/.claude/logs/merge-queue.json` exactly as it was, so re-feeding it through the *existing* `approve()` path (same one a fresh click uses) is enough to resume it; no new queue state or store method needed. For "wait, bounded, then proceed anyway," reuses `GET /merge-queue`'s existing `running` field (already served for MR Review) instead of adding a new endpoint. Testing reuses the exact fixture pattern already in `dashboard/test/merge_queue.test.js` (`world()` + real `createQueueStore` against a temp file) and the text-assertion pattern already in `lib/tests/test_rebuild_script.py` for `rebuild_and_install.sh` (that script is never executed in tests; its ordering/behavior is checked by reading the source).

**Simplest sufficient approach:** no new abstractions. AC1 is a bounded poll-and-wait inserted before one existing `launchctl kickstart -k` call. AC2 is wiring `takeInterruptedMerges()`'s already-existing output back into the already-existing `mergeQueue.approve()`, instead of only using it to paint the dashboard red. "Front of the queue" needs no new ordering mechanism: the interrupted PR's `approvedAt` already predates anything approved after the crash (the webhook was down, so nothing *could* have jumped ahead of it on this machine's queue), so dedupe-and-reapprove already puts it first.

**Token/compute cost:** near zero — a few curl polls (5s apart, bounded) in a background-spawned shell script, and a couple of already-open-file reads at webhook startup. No new processes, no new timers (`dashboard/test/polling_guard.test.js` forbids new recurring timers in the dashboard source anyway — this stays a bounded, one-shot loop inside a bash script, outside that guard's scope).

**Phone-OS direction:** indirect — reliability of the one shared merge pipeline that every machine's dashboard/phone reads from.

**User impact:** removes a silent stall that needed Gil to notice and manually re-click Approve. More capable (nothing to babysit), not more passive (nothing he'd otherwise learn by doing this by hand).

**North-star correction:** the ticket cites "North star 1," but `docs/north-stars.md`'s North star 1 is about minimising resources, not about reducing owner involvement. The actual fit is **North star 2**'s stated precondition — *"Reliability is its precondition: nothing may break silently"* — which is exactly what this ticket closes (a merge dying silently until a human notices). Noting the correction rather than silently keeping the ticket's number.

**Machine:** no specific machine; this is server-side webhook/queue code plus a shell script, identical on every Mac that runs `com.marvin.dashboard-webhook`.

## Current behavior (read before designing)

- `dashboard/webhook-server/merge_progress.js:65` `takeInterruptedMerges()` already detects a merge that was running when the process died (via `~/.claude/logs/merge-inflight.json`), logs `"... Approve again."`, and returns one event per lost merge — but `dashboard/webhook-server/index.js:496` only forwards that event to the dashboard's refresh port. The comment right above it (lines 493-495) states the current policy explicitly: *"Resuming is not attempted... Approve again is safe."* This ticket overturns that one documented decision.
- The merge-queue's own store (`createQueueStore`, `~/.claude/logs/merge-queue.json`) is **not** touched by a hard process kill: nothing calls `store.merged`/`store.fail`/`store.hold` before the process dies, so the interrupted PR's queue item survives untouched. `mergeQueue.kickAll()` already runs on every startup (`index.js:510`) and *could* pick it up generically — but only if nothing earlier in that async chain (facts refresh, GitHub reads) fails right at the fragile moment of a fresh restart, and only as a side effect nobody asserts. AC2's fix makes resumption a direct, deliberate, specifically-tested effect of `takeInterruptedMerges()`'s output, not an accidental side effect of a generic sweep.
- There is also a separate, already-shipped, dashboard-side (Electron main process) retry path — `approval_ledger.js` + `approval_retry.js` + `approve_flow.js` (owner decision on #766) — that retries a ledger entry marked `interrupted` up to 3 times, on the same Mac, triggered by a "webhook started" announcement. That system stays as-is (it's a useful cross-machine/dashboard-closed backstop); it only fires when a dashboard that made the original click is open to hold the ledger entry. This ticket's fix is **server-side**, so resumption no longer depends on any dashboard being open at all — matching the ticket's "the owner re-approved" framing (today, nothing resumes it without a human/dashboard in the loop; the fix makes the webhook itself responsible).
- `dashboard/scripts/rebuild_and_install.sh`'s last step (lines 82-87) calls `launchctl kickstart -k ...` on the merge-server launchd job unconditionally, whenever it's loaded — with no awareness of whether it's mid-merge. Both callers of this script (`dashboard/webhook-server/merge.js:1109` `spawnFn(...).unref()` and `lib/dashboard_rebuild.py:89` `subprocess.Popen(..., start_new_session=True)`) run it detached/backgrounded and never wait on it, so the script itself can safely block for several minutes without affecting anything upstream.
- A second, unrelated restart path — `lib/webhook_restart.py` (restarts the webhook when its own code is stale, on the 30-minute code-sync cycle) — has the exact same unconditional `launchctl kickstart -k` issue, but the ticket's "What to build" names only `rebuild_and_install.sh`. Flagged as a Decision below rather than silently expanded into scope.

## Tests to write first

All new tests reuse existing fixtures/conventions (`createMergeQueue`+`createQueueStore`+`world()` from `merge_queue.test.js`; text-position assertions from `test_rebuild_script.py`); nothing here is tested against a mock GitHub — `merge_queue.test.js`'s `world()` already behaves like the real gate (closes PRs, moves stacked PRs, etc.), so these exercise the real collaborator.

**`dashboard/test/merge_queue.test.js`** (new `describe('resuming an interrupted merge')`, testing a new exported `resumeInterrupted(queue, lost, { repoOf, by })` in `merge_queue.js`):
1. A PR still sitting in `items[]` with nothing recorded about it (simulating a hard-killed process: `store.add()` was called, nothing else) resumes and merges when `resumeInterrupted` is called against a **fresh** `createMergeQueue` over the same store file — i.e., what "after a restart" looks like. (The "goes back to the front" claim: assert it's the one `w.run` is called for first, even when another PR was approved — i.e. given a later `approvedAt` — in between.)
2. An interrupted PR that merged or closed on GitHub while the webhook was down is dropped (removed from `store.forRepo(repo).items`), and `w.run` is never called for it — reusing `evaluate()`'s existing `dropped` logic, no special-casing.
3. Two interrupted PRs across two different repos both resume independently (two drains at once) — concurrency case, reusing the queue's existing per-repo `busy` guard.
4. Calling `resumeInterrupted` twice for the same still-queued PR (two overlapping triggers, e.g. two rebuilds racing) does not duplicate the queue entry or run it twice concurrently — reuses `store.add`'s existing dedupe and `drain`'s existing `busy`/`again` reentrancy guard.
5. Misuse: empty `lost` list is a no-op; an entry whose URL doesn't resolve to a known repo (`repoOf` returns `null`) is skipped, not thrown.

**`dashboard/test/merge_gate_progress.test.js`** (extends the existing `'a webhook restart mid-merge'` describe block):
6. The existing assertion (`lines[0]` matches `/interrupted: the webhook restarted while it was at "tests"/`) must still pass unchanged (new wording only appends after that prefix — verifies I didn't break the prefix other code/tests key off).
7. New: the full log line and the returned event no longer say "Approve again"; they say it resumes/rejoins the queue.

**Update, not new** (text changed, so the existing assertion must change with it — "verify fails when code changes without a test changing"): the 4 existing hardcoded-string assertions in `dashboard/test/merge_ops.test.js:162`, `dashboard/test/approve_stream.test.js:67`, `dashboard/test/merge_progress_view.test.jsx:81,92` all currently assert `'The merge was interrupted when the webhook restarted. Approve again.'` verbatim; update them to the new wording in lockstep with `merge_ops.js`'s `INTERRUPTED_REASON`, `approve_stream.js`'s literal, and `prState.js`'s literal (kept as three independent literals, matching today's — unrelated — duplication; `src/` cannot import from `electron/main/`, and `approve_stream.js`→`merge_ops.js` dedup is a separate, out-of-scope cleanup).

**`lib/tests/test_rebuild_script.py`** (new tests, following its established "read the script text" style — this script is never executed in CI):
8. The restart step polls something before calling `launchctl kickstart -k` (a marker for the wait loop appears, positioned after `"installing to $DEST"` i.e. after the app is already rebuilt/installed/relaunched, per "the app itself can still be rebuilt and relaunched meanwhile") and before `launchctl kickstart -k`.
9. The wait is bounded: a numeric bound exists and the loop has an exit condition that doesn't depend on the probe ever succeeding (covers "a merge that takes longer than the wait bound").
10. `launchctl kickstart -k` is still called unconditionally after the wait block (not nested only inside an "idle" branch) — covers "proceeds anyway" after the bound.
11. The probe is defused against `set -euo pipefail` (curl output/exit status can't trip the `ERR` trap) — covers "the merge server is unreachable/mid-restart during the poll" (also exercises "two rebuilds in a row": a second script's poll must survive the first one's restart making the server briefly unreachable).
12. A giving-up-on-the-wait message is printed (so a long stall is visible in `dashboard-rebuild.log`, not silent).

## Decisions
<!-- marvin:decisions -->
### webhook_restart_scope: `lib/webhook_restart.py` has the exact same unconditional `launchctl kickstart -k` (a different trigger: stale webhook code on the 30-min code-sync cycle, not a rebuild). Fix it in this PR too, or leave it for a follow-up ticket?
- [ ] A: Fix it in this PR (same wait-before-restart treatment, reusing the same pattern)
- [ ] B: Leave it — file a follow-up ticket instead (ticket's "What to build" only names `rebuild_and_install.sh`)

## Task List

1. `dashboard/webhook-server/merge_queue.js`: add `export function resumeInterrupted(queue, lost, { repoOf, by = 'auto' } = {})` — for each `{url}` in `lost`, resolve its repo and call `queue.approve(repo, url, { by })`; skip entries with no resolvable repo.
2. Tests 1-5 above in `dashboard/test/merge_queue.test.js`.
3. `dashboard/webhook-server/index.js`: in the `server.listen` startup callback, after the existing `takeInterruptedMerges()` loop that forwards refresh pings, call `resumeInterrupted(mergeQueue, lost, { repoOf: repoOfPr })` (reusing the already-defined `repoOfPr`), logging a warning on rejection. Update the now-stale comment (lines 493-495) that says "Resuming is not attempted."
4. `dashboard/webhook-server/merge_progress.js`: update the log line in `takeInterruptedMerges()` (line 73) to say it resumes from the queue instead of "Approve again," preserving the existing matched prefix. Test 7 above; confirm test 6 still passes.
5. Update `INTERRUPTED_REASON` in `dashboard/electron/main/merge_ops.js:12`, the literal in `dashboard/electron/main/approve_stream.js:33`, and the literal in `dashboard/src/lib/prState.js:65` to the same new wording (leave the unrelated 45-minute-expiry message in `merge_ops.js:23` alone — different failure class).
6. Update the 4 existing test assertions listed above to match the new wording.
7. `dashboard/scripts/rebuild_and_install.sh`: before the existing `launchctl kickstart -k "gui/$(id -u)/com.marvin.dashboard-webhook"` call, add a bounded poll of `GET http://127.0.0.1:${PORT:-7878}/merge-queue` (any repo's `running` truthy = still merging), ~5s interval, ~10-minute bound, defused against `set -e`; log once if the bound is hit; then restart unconditionally either way.
8. Tests 8-12 above in `lib/tests/test_rebuild_script.py`.
9. `dashboard/webhook-server/README.md:29-30`: one-clause update noting an in-flight merge resumes from the queue on restart, not just "reported as interrupted."
10. `CONTEXT.md`'s "Merge queue" section (~line 1577): one bullet documenting that a merge the webhook finds interrupted at startup is re-approved automatically (marvin#1106), dropped like any other if it merged/closed while the webhook was down.
11. Resolve the Decision above; if A, repeat steps 7-8's pattern for `lib/webhook_restart.py` (+ its own test file `lib/tests/test_webhook_restart.py`).