## North-star fit

**Reuses:** the existing marvin#231 merge-queue `attach` pattern (`merge_queue.js`'s `drain()`/`approve()`, already used for "an Approve that is not next is answered at once with its place" — `dashboard/test/merge_queue.test.js:202`) and the existing preflight-assertion pattern (`assertTargetsBase`/`assertNotSentBack` in `merge.js`, each a cheap `gh pr view` check that fails open and throws a `MergeFailure(refusal(...))`). No new infrastructure, no new endpoint, no distributed lock — both gaps close by extending patterns already in the file.

**Why simplest sufficient:** I read the current code (not the ticket's stale `merge.js:424-449,606-617` / `index.js:60` line citations, which predate the #231 queue built 2026-10-30) and found the real, current gap is narrower than the ticket's evidence suggests:
- The queue **already** prevents a literal second gate run for one URL (proven by the existing passing test `merge_queue.test.js:186`, "two Macs approving the same PR add it once and merge it once"). So no new dedup-by-URL logic is needed.
- The actual bug is in `index.js`'s `/approve` handler: a second request for a URL that's **already running** gets an immediate `409 ALREADY_MERGING` (`index.js:286-289`) — ending that caller's stream on a placeholder, never on the real outcome. That's AC1's gap.
- `mergePrUnqueued` (`merge.js:847`) never checks the PR's GitHub `state`, so approving an already-merged PR falls through to `gh pr merge`, which fails with an unclassified, confusing error instead of a clean refusal. That's AC2's gap.

**Where it spends/saves tokens:** spends a little (one new assert function, one small queue extension); saves materially downstream — a clean `ALREADY_MERGED`/`PR_CLOSED` refusal is a classified code (`failure.js`'s `refusal()`), so neither the pipeline nor a future debugging session has to decode an "UNKNOWN" `gh pr merge` failure again.

**Phone-OS direction:** low relevance; this is backend correctness on a shared service both the desktop and phone approve into — it does make that shared service more trustworthy, which matters for "every machine works, none overloaded" (two Macs both legitimately clicking Approve is normal multi-device use, not misuse).

**Capable vs. passive:** purely backend; no UI behavior for the owner to learn or lose. It removes a confusing failure message, which keeps him from having to investigate a spurious error by hand.

**Machine:** no machine-specific work; same webhook process, any Mac.

## Scope note (read before the tests)

The ticket's title also names "two Macs" as a trigger. A **true** simultaneous click from two *separate* webhook processes (two Macs, each running its own `merge.js`/`index.js`) is not fully closable without a distributed lock, which nothing else in this codebase has and which north star 1 (minimal sufficient mechanism) argues against building for this ticket. AC2 (the `state === OPEN` check) is what actually protects that case in practice: whichever machine's gate finishes second now fails cleanly with "already merged" instead of today's confusing unclassified error. AC1 (joining the stream) is implemented at the single-process repo-queue level, which is where "Dedupe `/approve` by PR URL in the repo queue" literally lives, and is also exactly what fixes the realistic, testable cases: a double-click, a retried/dropped stream reconnecting to the same webhook, or two Mac dashboards that both happen to fail over to the same Mac's webhook.

## Decisions

None needed. The Fix text in the ticket is specific enough (dedupe in the repo queue; check `state === OPEN` first) that the remaining choices are implementation detail, not product tradeoffs:
- New refusal codes `ALREADY_MERGED` and `PR_CLOSED` (the latter is free — same `gh pr view --json state` read, same assert function, and directly backs the ticket's own "approve, deny, approve" break-it case).
- "Joins the stream" is scoped to a URL that is *actively running* right now, not one still waiting its queue turn (which keeps returning its position, as the queue has done since #231) — matches the ticket's own wording ("joins the **running** attempt's stream") and avoids holding an HTTP connection open for a potentially long queue wait.

## Tests first

In `dashboard/test/merge.test.js` (new `assertOpen`, alongside the existing `assertTargetsBase`/`assertNotSentBack` suites):
1. A `gh pr view` reporting `state: 'MERGED'` is refused with `payload.code === 'ALREADY_MERGED'`, message naming it plainly ("already merged").
2. A `gh pr view` reporting `state: 'CLOSED'` is refused with `payload.code === 'PR_CLOSED'`.
3. `state: 'OPEN'` resolves `undefined` (passes through).
4. The `gh pr view` call rejecting (network/tool failure) resolves `undefined` — fails open, same policy as the sibling asserts (a lookup hiccup must never block a good merge).
5. Garbled/non-JSON output from `gh pr view` resolves `undefined` — same fail-open policy, malformed-dependency-output case.
6. End-to-end: `mergePr(mergedPrUrl, exec, noopRebuild, noopRedispatch)` rejects with `payload.code === 'ALREADY_MERGED'` and the mock `exec` is never called with `['pr', 'merge', ...]` — proves it short-circuits before any gate work, not just that it eventually fails at the merge step.

In `dashboard/test/merge_queue.test.js` (new follower/join mechanism in `createMergeQueue`):
7. **Core case.** Two `approve()` calls for the same URL, each with its own `attach`, where the second arrives while the first is already running (busy, `running.get(repo) === url`): the second attach's `queued()` is never called, and the `run()` invocation that is in flight is handed a `followers` array containing it. Only one `run()` call happens total.
8. **Repeats/concurrency.** Three overlapping `approve()` calls for the same running URL: all three are followers (or one is `mine` + two followers); still exactly one `run()` call.
9. **Dependency failure.** The in-flight run's outcome is a failure (`reengaged`/sent-back) or `run()` itself throws synchronously: followers are still resolved with that outcome via the `followers` array — none are left to hang forever (today's equivalent of silently never answering a dropped-and-rejoined stream).
10. **Regression guard.** A second `approve()` for the same URL while it is merely *queued* behind another PR (not yet running) is answered at once with its queued position exactly as before (`merge_queue.test.js:202`'s existing case) — proves the new follower path is scoped to "actively running" only, not "queued."
11. **Trailing-edge race (stale state).** A second `approve()` arrives in the narrow window right after the run finishes (`running.delete(repo)` already happened) but before the queue has fully settled: it is treated as a fresh approve, not stuck waiting on a follower list for a run that's already over.
12. **"Approve, deny, approve within a second."** `approve(url)` (queued, not yet run) → the next `load()` reports the PR as `sentBack` (what `deny.js`'s `send_feedback` produces on GitHub, exactly as `enrichForOrder` already encodes it) → `approve(url)` again: the queue entry is a single item (not duplicated), its state is "waiting: sent back for rework," and no `run()` happens while that holds — then clearing `sentBack` and kicking merges it exactly once. This is a characterization test over existing `enrichForOrder`/`ownReason` behavior, guarding that the new follower logic doesn't disturb it.

Explicitly not tested (scoped out, with reasons):
- **Wrong permissions** — no new permission boundary is introduced by this change.
- **Huge/malformed `/approve` request bodies** — `readJsonBody` in `index.js` has no size cap at all (unlike `readBody(req, limit)` used elsewhere in the same file), which is a real latent gap, but it's pre-existing, orthogonal to dedup/state-check, and not named in this ticket's acceptance criteria; flagging it rather than silently expanding scope.
- **True cross-process (two separate webhook Macs) simultaneous click** — see "Scope note" above; not mechanically testable without standing up two real server processes, and AC2 is what makes that case fail cleanly rather than confusingly.

## Task List

1. `dashboard/webhook-server/pr_snapshot.js`: add `'state'` to `SNAPSHOT_FIELDS` so the new check rides the existing combined preflight read (no extra `gh` call).
2. `dashboard/webhook-server/merge.js`: add `assertOpen(prUrl, exec)`, placed with and styled like `assertTargetsBase`/`assertNotSentBack` — reads `state`, fails open on any read/parse error, refuses `ALREADY_MERGED` for `MERGED` and `PR_CLOSED` for `CLOSED`, resolves otherwise. Call it first in `mergePrUnqueued`, before `assertTargetsBase`.
3. `dashboard/webhook-server/merge_queue.js`: in `createMergeQueue`, add a `followers` map (`repo -> Map(url -> attach[])`). In `drain()`, when `busy.has(repo)` and the incoming `attach.url === running.get(repo)`, push it onto that URL's followers list instead of calling `attach.queued(...)`. When the run for that URL starts, collect and clear its followers list and pass it to `run(url, mine, followers)` (new third parameter).
4. `dashboard/webhook-server/index.js`: remove the premature `if (mergeQueue.isRunning(prUrl)) { 409 ALREADY_MERGING }` shortcut (the current lines ~286-289) for valid PR URLs, so every approve flows into `mergeQueue.approve()`. Update the `run:` callback passed to `createMergeQueue({...})` to accept `followers` and, after `runMerge` resolves, call `.reply.result(status, body)` on every follower exactly as it already does for the primary `attach`.
5. Write and land the tests in the "Tests first" list (1-12) before/alongside steps 1-4, per TDD.
6. Run the full Python + dashboard suites (not just the touched files) before calling this done, per the full-suites-before-merge rule.
7. No UI-visible change, so no screenshots are needed for the third acceptance criterion ("if anything visible changes") — note this plainly in the PR rather than skipping it silently.