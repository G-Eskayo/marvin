1. `merge.js`: add `assertStillOpen(prUrl, exec)` — `gh pr view --json state`, refuse `ALREADY_MERGED` / `PR_CLOSED` via the existing `refusal()` + `MergeFailure` pattern, fail open on any read/parse error. Call it first in `mergePrUnqueued`, before `progress('fetching', 'running')` and before `gateContext`.
2. `pr_snapshot.js`: add `'state'` to `SNAPSHOT_FIELDS` so this new read folds into the existing one-call snapshot.
3. `merge.test.js`: tests 1–7 above.
4. `pr_snapshot.test.js` (or wherever the existing P5 call-count test lives): test 8.
5. `merge_progress.js`: add `createMergeJoin()` next to `createMergeLatch`/`alreadyMergingBody` — `join(url, reply)`, `event(url, ev)`, `finish(url, status, body)` (clears the url's entry).
6. `merge_failover.test.js` (or `merge_progress.test.js`): tests 9–12.
7. `index.js`: instantiate `mergeJoin = createMergeJoin()`; in the `/approve` handler, compute `probe = payload?.probe === true || payload?.by === 'memory-queue'` and, when `mergeQueue.isRunning(prUrl)` is true, branch on `probe` (old 409 path) vs. `mergeJoin.join(prUrl, reply)` (new path, return without responding further) — keep the `isRunning` check and the `join` call adjacent with no `await` between them.
8. `index.js`: in `runMerge`'s tracker `emit`, also call `mergeJoin.event(prUrl, ev)`; at both `return` points (success and catch), call `mergeJoin.finish(prUrl, status, body)` before returning.
9. New or extended test file alongside `merge_failover.test.js`'s existing webhook-harness tests: tests 13–21.
10. `approve_stream.js`: accept a `probe` option; include `probe: true` in the request body only when set.
11. `approve_flow.js`: pass `probe: retry` on the primary `send(...)` call (line ~94) and the `backupForMemory` failover `send(...)` call (line ~100).
12. `approve_stream.test.js` / `approve_flow.test.js` (whichever currently covers these): tests 22–23.
13. Run the full merge/dashboard-webhook suite (not just the new files) to confirm nothing in `merge_queue.test.js`, `merge_memory_wait.test.js`, or `merge_memory_guard.test.js` regresses — those exercise the `ALREADY_MERGING`/`by: 'memory-queue'` paths this change must leave untouched.
14. Screenshots: not expected to be needed — this is a backend dedupe/preflight fix with no new UI states or strings; `MergeProgress.jsx` and the card components are unchanged, just driven by correct events. Re-check once implemented: if any dashboard-visible text or state actually changes, pin 900px and 1440px screenshots on the PR per AC3.